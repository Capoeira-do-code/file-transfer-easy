package tunnel

import (
	"bufio"
	"context"
	"errors"
	"io"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
)

// quickTunnelURL matches the public hostname cloudflared prints once the quick
// tunnel is up.
var quickTunnelURL = regexp.MustCompile(`https://[a-zA-Z0-9][a-zA-Z0-9-]*\.trycloudflare\.com`)

// startTimeout is how long we wait for cloudflared to announce a URL before
// giving up on it.
const startTimeout = 45 * time.Second

// session is one cloudflared process and the plumbing that watches it.
type session struct {
	cmd     *exec.Cmd
	writer  *io.PipeWriter
	exited  chan struct{}
	stopped bool // guarded by Runner.mu; belongs to this process only
}

// Runner supervises one cloudflared process at a time.
type Runner struct {
	mu      sync.Mutex
	current *session

	binDir string
	log    Logf
}

// NewRunner returns a runner that caches cloudflared inside binDir.
func NewRunner(binDir string, log Logf) *Runner {
	return &Runner{binDir: binDir, log: log}
}

func (r *Runner) logf(level, format string, args ...any) {
	if r.log != nil {
		r.log(level, format, args...)
	}
}

// Running reports whether a cloudflared process is currently alive.
func (r *Runner) Running() bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	return r.current != nil
}

// Start launches a quick tunnel pointing at the given local port and blocks
// until cloudflared announces the public URL, or the attempt fails.
//
// onExit is called from a background goroutine if the process dies on its own;
// it is not called when the tunnel is stopped deliberately.
func (r *Runner) Start(ctx context.Context, port int, onExit func(error)) (string, error) {
	r.Stop()

	binary, err := Ensure(ctx, r.binDir, r.log)
	if err != nil {
		return "", err
	}

	localTarget := "http://127.0.0.1:" + strconv.Itoa(port)
	cmd := exec.CommandContext(ctx, binary, "tunnel", "--no-autoupdate", "--url", localTarget)
	hideConsoleWindow(cmd)

	// cloudflared splits its output across stdout and stderr, and prints the
	// banner carrying the URL on stderr. Merge both into a single reader.
	reader, writer := io.Pipe()
	cmd.Stdout = writer
	cmd.Stderr = writer

	r.logf("info", "Iniciando túnel de Cloudflare hacia %s", localTarget)
	if err := cmd.Start(); err != nil {
		writer.Close()
		return "", errors.New("no se pudo iniciar cloudflared: " + err.Error())
	}

	current := &session{cmd: cmd, writer: writer, exited: make(chan struct{})}
	r.mu.Lock()
	r.current = current
	r.mu.Unlock()

	urls := make(chan string, 1)
	go r.drain(reader, urls)

	var waitErr error
	go func() {
		waitErr = cmd.Wait()
		// Closing the writer ends the scanner in drain once it has consumed
		// everything the process wrote.
		writer.Close()
		close(current.exited)

		r.mu.Lock()
		deliberate := current.stopped
		if r.current == current {
			r.current = nil
		}
		r.mu.Unlock()

		if !deliberate && ctx.Err() == nil && onExit != nil {
			onExit(waitErr)
		}
	}()

	select {
	case <-ctx.Done():
		r.Stop()
		return "", ctx.Err()

	case url := <-urls:
		r.logf("info", "Túnel activo: %s", url)
		return url, nil

	case <-current.exited:
		if waitErr != nil {
			return "", errors.New("cloudflared terminó de forma inesperada: " + waitErr.Error())
		}
		return "", errors.New("cloudflared terminó antes de publicar una URL")

	case <-time.After(startTimeout):
		r.Stop()
		return "", errors.New("cloudflared no publicó una URL a tiempo")
	}
}

// drain forwards cloudflared output to the log and reports the first public URL
// it sees on urls.
func (r *Runner) drain(reader io.Reader, urls chan<- string) {
	scanner := bufio.NewScanner(reader)
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	sent := false

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || isBannerNoise(line) {
			continue
		}
		if !sent {
			if match := quickTunnelURL.FindString(line); match != "" {
				sent = true
				select {
				case urls <- match:
				default:
				}
			}
		}
		r.logf("tunnel", "%s", line)
	}
}

// isBannerNoise filters the ASCII box cloudflared draws around the URL, which
// is pure decoration in a log view.
func isBannerNoise(line string) bool {
	return strings.Trim(line, "+-| ") == ""
}

// Stop terminates the tunnel, escalating to a kill if it does not exit in time.
func (r *Runner) Stop() {
	r.mu.Lock()
	current := r.current
	r.current = nil
	if current != nil {
		current.stopped = true
	}
	r.mu.Unlock()

	if current == nil || current.cmd.Process == nil {
		return
	}
	r.logf("info", "Deteniendo el túnel…")

	if err := terminate(current.cmd); err != nil {
		current.cmd.Process.Kill()
	}
	select {
	case <-current.exited:
	case <-time.After(5 * time.Second):
		current.cmd.Process.Kill()
		<-current.exited
	}
}

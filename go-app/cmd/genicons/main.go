// Command genicons renders every icon the app ships from one vector
// definition, so the mark stays identical across the dock, the tray, the
// Windows .ico and the macOS .icns.
//
// Run it from the go-app directory:
//
//	go run ./cmd/genicons
//
// Shapes are described in a resolution-independent 0..1 space and rasterised
// with 4x supersampling, which keeps the edges clean at every size without
// pulling in a rasteriser dependency.
package main

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"image"
	"image/color"
	"image/png"
	"math"
	"os"
	"path/filepath"
)

// supersample is the linear oversampling factor used for anti-aliasing.
const supersample = 4

// shape reports whether a point in the unit square is inside the mark.
type shape func(x, y float64) bool

// ---------------------------------------------------------------- primitives

func roundedRect(x0, y0, x1, y1, radius float64) shape {
	return func(x, y float64) bool {
		if x < x0 || x > x1 || y < y0 || y > y1 {
			return false
		}
		// Only the four corner boxes need the distance test.
		cx, cy := x, y
		switch {
		case x < x0+radius:
			cx = x0 + radius
		case x > x1-radius:
			cx = x1 - radius
		default:
			return true
		}
		switch {
		case y < y0+radius:
			cy = y0 + radius
		case y > y1-radius:
			cy = y1 - radius
		default:
			return true
		}
		return math.Hypot(x-cx, y-cy) <= radius
	}
}

func triangle(ax, ay, bx, by, cx, cy float64) shape {
	sign := func(x1, y1, x2, y2, x3, y3 float64) float64 {
		return (x1-x3)*(y2-y3) - (x2-x3)*(y1-y3)
	}
	return func(x, y float64) bool {
		d1 := sign(x, y, ax, ay, bx, by)
		d2 := sign(x, y, bx, by, cx, cy)
		d3 := sign(x, y, cx, cy, ax, ay)
		hasNeg := d1 < 0 || d2 < 0 || d3 < 0
		hasPos := d1 > 0 || d2 > 0 || d3 > 0
		return !(hasNeg && hasPos)
	}
}

func union(shapes ...shape) shape {
	return func(x, y float64) bool {
		for _, s := range shapes {
			if s(x, y) {
				return true
			}
		}
		return false
	}
}

func subtract(base, cut shape) shape {
	return func(x, y float64) bool { return base(x, y) && !cut(x, y) }
}

// ---------------------------------------------------------------- the artwork

// glyph is the share mark: an arrow rising out of an open tray.
func glyph() shape {
	shaft := roundedRect(0.445, 0.255, 0.555, 0.605, 0.055)
	head := triangle(0.500, 0.185, 0.310, 0.400, 0.690, 0.400)

	// The tray is a thick rounded rect with its top half carved away, leaving
	// an upward-opening bracket the arrow appears to rise from.
	trayOuter := roundedRect(0.245, 0.545, 0.755, 0.815, 0.075)
	trayInner := roundedRect(0.335, 0.455, 0.665, 0.725, 0.045)
	tray := subtract(trayOuter, trayInner)

	return union(shaft, head, tray)
}

// tint is the colour ramp used on the app icon, a soft vertical teal gradient.
func tint(y float64) color.RGBA {
	top := color.RGBA{R: 0x1f, G: 0xb0, B: 0x99, A: 0xff}
	bottom := color.RGBA{R: 0x0b, G: 0x6f, B: 0x63, A: 0xff}
	mix := func(a, b uint8) uint8 { return uint8(float64(a) + (float64(b)-float64(a))*y) }
	return color.RGBA{
		R: mix(top.R, bottom.R),
		G: mix(top.G, bottom.G),
		B: mix(top.B, bottom.B),
		A: 0xff,
	}
}

// renderApp draws the full app icon: a tinted squircle with the glyph knocked
// out in white.
func renderApp(size int) *image.RGBA {
	// Apple's icon grid insets the artwork slightly; matching it keeps the icon
	// from looking oversized next to system apps.
	plate := roundedRect(0.04, 0.04, 0.96, 0.96, 0.2237*0.92)
	mark := glyph()

	return render(size, func(x, y float64) (color.RGBA, float64) {
		if !plate(x, y) {
			return color.RGBA{}, 0
		}
		if mark(x, y) {
			return color.RGBA{R: 0xff, G: 0xff, B: 0xff, A: 0xff}, 1
		}
		return tint(y), 1
	})
}

// renderGlyph draws the bare mark in a single colour, for tray icons.
func renderGlyph(size int, fill color.RGBA) *image.RGBA {
	mark := glyph()
	// Tray icons need breathing room inside their slot, so the glyph is scaled
	// down and centred rather than filling the canvas.
	const inset = 0.08
	scale := 1.0 / (1.0 - 2*inset)

	return render(size, func(x, y float64) (color.RGBA, float64) {
		gx := (x-0.5)/scale + 0.5
		gy := (y-0.5)/scale + 0.5
		if gx < 0 || gx > 1 || gy < 0 || gy > 1 || !mark(gx, gy) {
			return color.RGBA{}, 0
		}
		return fill, 1
	})
}

// render rasterises a paint function with supersampled coverage.
func render(size int, paint func(x, y float64) (color.RGBA, float64)) *image.RGBA {
	img := image.NewRGBA(image.Rect(0, 0, size, size))
	samples := supersample * supersample

	for py := 0; py < size; py++ {
		for px := 0; px < size; px++ {
			var r, g, b, coverage float64

			for sy := 0; sy < supersample; sy++ {
				for sx := 0; sx < supersample; sx++ {
					x := (float64(px) + (float64(sx)+0.5)/supersample) / float64(size)
					y := (float64(py) + (float64(sy)+0.5)/supersample) / float64(size)

					c, alpha := paint(x, y)
					if alpha <= 0 {
						continue
					}
					r += float64(c.R) * alpha
					g += float64(c.G) * alpha
					b += float64(c.B) * alpha
					coverage += alpha
				}
			}

			if coverage == 0 {
				continue
			}
			// Premultiplied alpha: the accumulated colour is already weighted
			// by coverage, so it only needs scaling by the sample count.
			img.SetRGBA(px, py, color.RGBA{
				R: uint8(math.Round(r / float64(samples))),
				G: uint8(math.Round(g / float64(samples))),
				B: uint8(math.Round(b / float64(samples))),
				A: uint8(math.Round(coverage / float64(samples) * 255)),
			})
		}
	}
	return img
}

// ---------------------------------------------------------------------- output

func writePNG(path string, img image.Image) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	file, err := os.Create(path)
	if err != nil {
		return err
	}
	defer file.Close()

	encoder := png.Encoder{CompressionLevel: png.BestCompression}
	return encoder.Encode(file, img)
}

// writeICO packs several sizes into a Windows .ico. Entries are stored as PNG,
// which every Windows version since Vista reads natively.
func writeICO(path string, sizes []int, render func(int) *image.RGBA) error {
	type entry struct {
		size int
		data []byte
	}

	entries := make([]entry, 0, len(sizes))
	for _, size := range sizes {
		var buffer bytes.Buffer
		if err := png.Encode(&buffer, render(size)); err != nil {
			return err
		}
		entries = append(entries, entry{size: size, data: buffer.Bytes()})
	}

	var out bytes.Buffer
	// ICONDIR: reserved, type 1 (icon), image count.
	binary.Write(&out, binary.LittleEndian, uint16(0))
	binary.Write(&out, binary.LittleEndian, uint16(1))
	binary.Write(&out, binary.LittleEndian, uint16(len(entries)))

	// Directory entries are fixed width, so the first image starts right after.
	offset := 6 + 16*len(entries)
	for _, e := range entries {
		dimension := byte(e.size)
		if e.size >= 256 {
			// 0 means 256 in the ICO format.
			dimension = 0
		}
		out.WriteByte(dimension)                                     // width
		out.WriteByte(dimension)                                     // height
		out.WriteByte(0)                                             // palette size
		out.WriteByte(0)                                             // reserved
		binary.Write(&out, binary.LittleEndian, uint16(1))           // colour planes
		binary.Write(&out, binary.LittleEndian, uint16(32))          // bits per pixel
		binary.Write(&out, binary.LittleEndian, uint32(len(e.data))) // size
		binary.Write(&out, binary.LittleEndian, uint32(offset))      // offset
		offset += len(e.data)
	}
	for _, e := range entries {
		out.Write(e.data)
	}

	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return err
	}
	return os.WriteFile(path, out.Bytes(), 0o644)
}

func main() {
	const dir = "build/icons"

	black := color.RGBA{R: 0, G: 0, B: 0, A: 0xff}
	white := color.RGBA{R: 0xff, G: 0xff, B: 0xff, A: 0xff}

	steps := []struct {
		name string
		run  func() error
	}{
		{"appicon.png", func() error {
			return writePNG(filepath.Join(dir, "appicon.png"), renderApp(1024))
		}},
		{"tray-template.png", func() error {
			// macOS template icons are pure black plus alpha; the system
			// recolours them for light and dark menu bars.
			return writePNG(filepath.Join(dir, "tray-template.png"), renderGlyph(44, black))
		}},
		{"tray.png", func() error {
			// Windows tray icons sit on a dark taskbar far more often than not.
			return writePNG(filepath.Join(dir, "tray.png"), renderGlyph(32, white))
		}},
		{"icon.ico", func() error {
			return writeICO(filepath.Join(dir, "icon.ico"),
				[]int{16, 24, 32, 48, 64, 128, 256}, renderApp)
		}},
	}

	// The .icns members are written as loose files; the macOS build script
	// folds them into an iconset with iconutil.
	for _, size := range []int{16, 32, 64, 128, 256, 512, 1024} {
		steps = append(steps, struct {
			name string
			run  func() error
		}{
			name: fmt.Sprintf("iconset/icon_%d.png", size),
			run: func() error {
				return writePNG(filepath.Join(dir, "iconset", fmt.Sprintf("icon_%d.png", size)), renderApp(size))
			},
		})
	}

	for _, step := range steps {
		if err := step.run(); err != nil {
			fmt.Fprintf(os.Stderr, "fallo al generar %s: %v\n", step.name, err)
			os.Exit(1)
		}
		fmt.Println("generado", filepath.Join(dir, step.name))
	}
}

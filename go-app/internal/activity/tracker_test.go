package activity

import "testing"

func TestForgottenVisitorStaysRemovedUntilPageReopens(t *testing.T) {
	tracker := New(nil)
	tracker.Visit("192.0.2.10", "test browser")
	visitors, _, _, _ := tracker.Snapshot()
	if len(visitors) != 1 || !tracker.Forget(visitors[0].ID) {
		t.Fatal("test visitor was not removed")
	}
	tracker.Seen("192.0.2.10", "heartbeat")
	visitors, _, _, _ = tracker.Snapshot()
	if len(visitors) != 0 {
		t.Fatal("heartbeat resurrected a removed visitor")
	}
	tracker.Visit("192.0.2.10", "reopened")
	visitors, _, _, _ = tracker.Snapshot()
	if len(visitors) != 1 {
		t.Fatal("reopening did not restore live presence")
	}
}

func TestBlockCancelsOnlyThatIPsTransfers(t *testing.T) {
	tracker := New(nil)
	blocked := tracker.StartTransfer("file", "a", "192.0.2.1", 100)
	other := tracker.StartTransfer("upload", "b", "192.0.2.2", 100)
	tracker.CancelIP("192.0.2.1")
	select {
	case <-blocked.Cancelled():
	default:
		t.Fatal("blocked transfer did not cancel")
	}
	select {
	case <-other.Cancelled():
		t.Fatal("another visitor's transfer was cancelled")
	default:
	}
}

func TestUploadCountsReceivedBytesSeparatelyFromDownloads(t *testing.T) {
	tracker := New(nil)
	transfer := tracker.StartTransfer("upload", "received.txt", "192.0.2.1", 123)
	tracker.FinishTransfer(transfer, "done")
	_, _, stats, _ := tracker.Snapshot()
	if stats.Downloads != 0 || stats.Bytes != 0 || stats.Uploads != 1 || stats.ReceivedBytes != 123 {
		t.Fatalf("wrong transfer counters: %+v", stats)
	}
}

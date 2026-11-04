package api

import "testing"

func TestNotificationReceiptValidatesClientReport(t *testing.T) {
	for _, body := range []string{`{}`, `{"type":"receipt","id":0,"status":"posted"}`, `{"type":"receipt","id":4,"status":"arbitrary log text"}`, `invalid`} {
		if _, ok := notificationReceipt([]byte(body)); ok {
			t.Fatalf("accepted invalid receipt: %s", body)
		}
	}
	r, ok := notificationReceipt([]byte(`{"type":"receipt","id":4,"status":"posted","capsule":true}`))
	if !ok || r.ID != 4 || !r.Capsule {
		t.Fatalf("lost valid receipt: %+v", r)
	}
}

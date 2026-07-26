package providers

import "testing"

func TestCloneMetadataPreservesCompressionMarkers(t *testing.T) {
	source := map[string]string{
		"compression":   "gzip",
		"original_size": "128",
		"file_id":       "file-1",
	}

	cloned := cloneMetadata(source)

	if cloned["compression"] != "gzip" || cloned["original_size"] != "128" {
		t.Fatalf("compression metadata was not preserved: %#v", cloned)
	}
	cloned["file_id"] = "changed"
	if source["file_id"] != "file-1" {
		t.Fatal("cloneMetadata returned an alias of the source map")
	}
}

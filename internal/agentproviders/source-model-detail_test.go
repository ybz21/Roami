package agentproviders

import (
	"encoding/json"
	"testing"
)

func TestSourceModelDetailDoesNotInferUnknownsOrExposeUnboundedData(t *testing.T) {
	var raw sourceModelWire
	if err := json.Unmarshal([]byte(`{"id":"m","name":"provider-credential","context_length":-1,"top_provider":{"max_completion_tokens":100000001},"supported_parameters":[],"architecture":{"input_modalities":["image","image","unexpected"]},"pricing":{"prompt":"NaN","completion":"-1"}}`), &raw); err != nil {
		t.Fatal(err)
	}
	row := raw.detail("m", "provider-credential")
	if row.Name != "" || row.Context != 0 || row.Output != 0 || row.InputPrice != nil || row.OutputPrice != nil || row.Tools == nil || *row.Tools || len(row.InputModalities) != 1 {
		t.Fatalf("invalid metadata projected: %+v", row)
	}
	row = (sourceModelWire{}).detail("unknown", "")
	if row.Tools != nil || row.Reasoning != nil || row.InputPrice != nil {
		t.Fatal("unknown metadata inferred")
	}
}

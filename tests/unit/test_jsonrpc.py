from zem.protocol import jsonrpc


def test_parse_good():
    assert jsonrpc.parse_line(b'{"jsonrpc":"2.0","id":1,"method":"tools/call"}\n')["id"] == 1


def test_parse_garbage():
    assert jsonrpc.parse_line(b"not json") is None
    assert jsonrpc.parse_line(b"[1,2]") is None
    assert jsonrpc.parse_line(b"\xff\xfe") is None


def test_roundtrip_is_single_line():
    out = jsonrpc.dumps({"a": "line1\nline2"})
    assert out.count(b"\n") == 1 and out.endswith(b"\n")


def test_blocked_shape():
    r = jsonrpc.blocked_response(7, "pipe-to-shell")
    assert r["id"] == 7 and r["result"]["isError"] is True

from __future__ import annotations

from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from video_caster.server.media_server import MediaServer


class FakeSource:
    def __init__(self, segments: dict[int, Path]) -> None:
        self.segments = segments
        self.asked: list[int] = []

    def playlist(self) -> str:
        return "#EXTM3U\n"

    async def segment(self, index: int) -> Path | None:
        self.asked.append(index)
        return self.segments.get(index)


async def client_for(server: MediaServer) -> TestClient:
    client = TestClient(TestServer(server._app))
    await client.start_server()
    return client


async def test_hls_routes_ask_the_source(tmp_path):
    seg = tmp_path / "seg-00003.ts"
    seg.write_bytes(b"mpegts")
    source = FakeSource({3: seg})
    server = MediaServer()
    server.register_hls("abc", source)
    client = await client_for(server)
    try:
        playlist = await client.get("/hls/abc/playlist.m3u8")
        assert await playlist.text() == "#EXTM3U\n"
        assert playlist.content_type == "application/vnd.apple.mpegurl"

        found = await client.get("/hls/abc/seg-00003.ts")
        assert await found.read() == b"mpegts"
        assert found.headers["Content-Type"] == "video/mp2t"

        assert (await client.get("/hls/abc/seg-00004.ts")).status == 404
        assert (await client.get("/hls/abc/other.ts")).status == 404
        assert (await client.get("/hls/gone/seg-00003.ts")).status == 404
        assert source.asked == [3, 4]
    finally:
        await client.close()

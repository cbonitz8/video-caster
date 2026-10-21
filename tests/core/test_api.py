from __future__ import annotations

import asyncio

import pytest
from aiohttp import ClientSession, WSServerHandshakeError, web
from pychromecast.error import RequestTimeout

from video_caster.casting.base import PlaybackStatus
from video_caster.core.api import create_app
from tests.conftest import LIVING_ROOM, make_video

TOKEN = "test-token"
LOCAL = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
async def client(aiohttp_client, engine):
    await engine.scan_devices()
    return await aiohttp_client(create_app(engine, TOKEN))


async def test_index_served(client):
    resp = await client.get("/")
    assert resp.status == 200
    assert "Video Caster" in await resp.text()


async def test_state(client):
    resp = await client.get("/api/state")
    assert resp.status == 200
    body = await resp.json()
    assert {d["name"] for d in body["devices"]} == {"Living Room", "Bedroom"}
    assert body["current"] is None


async def test_library(client):
    resp = await client.get("/api/library")
    assert set(await resp.json()) == {"continue", "shows", "movies", "newly_added"}


async def test_browse_roots_and_folder(client, watch_dir):
    roots = await (await client.get("/api/browse")).json()
    assert roots == [{"path": str(watch_dir), "name": "watch", "is_dir": True}]
    entries = await (await client.get("/api/browse", params={"path": str(watch_dir)})).json()
    assert [e["name"] for e in entries] == ["Movie.mkv"]


async def test_browse_refuses_outside_watch_folders(client, tmp_path):
    resp = await client.get("/api/browse", params={"path": str(tmp_path)})
    assert resp.status == 403
    assert "error" in await resp.json()


async def test_browse_missing_folder(client, watch_dir):
    resp = await client.get("/api/browse", params={"path": str(watch_dir / "nope")})
    assert resp.status == 404


async def test_cast_in_watch_folder(client, engine, video):
    engine.select_device(LIVING_ROOM.id)
    resp = await client.post("/api/cast", json={"path": str(video)})
    assert resp.status == 202
    assert await resp.json() == {"status": "casting", "device": "Living Room"}
    await engine.cast_task


async def test_cast_outside_needs_local_token(client, tmp_path):
    outside = make_video(tmp_path / "elsewhere" / "clip.mkv")
    assert (await client.post("/api/cast", json={"path": str(outside)})).status == 403
    resp = await client.post("/api/cast", json={"path": str(outside)}, headers=LOCAL)
    assert resp.status == 202
    assert (await resp.json())["status"] == "waiting_for_device"


async def test_cast_from_history_allowed(client, history, tmp_path):
    old = make_video(tmp_path / "old-folder" / "clip.mkv")
    await history.record_play(str(old), old.name, "dev", "Living Room", 100.0)
    resp = await client.post("/api/cast", json={"path": str(old)})
    assert resp.status == 202


async def test_cast_wrong_token_refused(client, video):
    resp = await client.post(
        "/api/cast", json={"path": str(video)}, headers={"Authorization": "Bearer nope"})
    assert resp.status == 403


async def test_cast_missing_file(client, watch_dir):
    resp = await client.post("/api/cast", json={"path": str(watch_dir / "gone.mkv")})
    assert resp.status == 404


@pytest.mark.parametrize("body", [
    {},
    {"path": 5},
    {"path": "relative.mkv"},
    {"path": "/x.mkv", "resume": "yes"},
    ["not", "an", "object"],
])
async def test_cast_rejects_bad_body(client, body):
    resp = await client.post("/api/cast", json=body)
    assert resp.status == 400
    assert "error" in await resp.json()


async def test_cast_rejects_non_json(client):
    resp = await client.post("/api/cast", data="not json")
    assert resp.status == 400


@pytest.mark.parametrize("body", [
    {}, {"level": "loud"}, {"level": None}, {"level": True}, {"level": float("nan")},
])
async def test_volume_rejects_bad_level(client, body):
    resp = await client.post("/api/playback/volume", json=body)
    assert resp.status == 400


async def test_volume(client, orchestrator):
    resp = await client.post("/api/playback/volume", json={"level": 0.5})
    assert resp.status == 200
    assert await resp.json() == {"ok": True}
    assert ("set_volume", 0.5) in orchestrator.calls


async def test_seek_offset(client, orchestrator):
    orchestrator.status = PlaybackStatus(state="playing", current_time=10.0, duration=100.0)
    resp = await client.post("/api/playback/seek", json={"offset": 10})
    assert resp.status == 200
    assert orchestrator.calls[-1] == ("seek", 20.0)


@pytest.mark.parametrize("body", [
    {}, {"position": "x"}, {"offset": None}, {"position": 1, "offset": 1},
])
async def test_seek_rejects_bad_body(client, body):
    resp = await client.post("/api/playback/seek", json=body)
    assert resp.status == 400


async def test_toggle_and_stop(client, orchestrator):
    assert (await client.post("/api/playback/toggle")).status == 200
    assert (await client.post("/api/playback/stop")).status == 200
    assert ("toggle_pause",) in orchestrator.calls
    assert ("stop_playback",) in orchestrator.calls


async def test_device_timeout_is_504(client, orchestrator):
    orchestrator.command_error = RequestTimeout("play", 10.0)
    resp = await client.post("/api/playback/toggle")
    assert resp.status == 504
    assert "timed out" in (await resp.json())["error"]


async def test_select_device(client):
    ok = await client.post("/api/devices/select", json={"device_id": LIVING_ROOM.id})
    assert ok.status == 200
    missing = await client.post("/api/devices/select", json={"device_id": "nope"})
    assert missing.status == 404


async def test_scan_accepted(client):
    resp = await client.post("/api/devices/scan")
    assert resp.status == 202


async def test_pin_without_request_is_409(client):
    resp = await client.post("/api/pairing/pin", json={"pin": "1234"})
    assert resp.status == 409


async def test_settings_get(client, watch_dir):
    body = await (await client.get("/api/settings")).json()
    assert body["watch_folders"] == [{"path": str(watch_dir), "available": True}]


async def test_settings_put_requires_token(client, tmp_path):
    change = {"recently_added_limit": 5}
    assert (await client.put("/api/settings", json=change)).status == 401
    bad = await client.put(
        "/api/settings", json=change, headers={"Authorization": "Bearer nope"})
    assert bad.status == 403
    ok = await client.put("/api/settings", json=change, headers=LOCAL)
    assert ok.status == 200
    assert (await ok.json())["recently_added_limit"] == 5


async def test_events_sends_state_then_pushes(client, engine):
    async with client.ws_connect("/api/events") as ws:
        first = await ws.receive_json(timeout=2)
        assert first["type"] == "state"
        assert first["data"]["selected_device"] is None
        engine.events.publish("error", {"message": "boom", "source": "test"})
        assert await ws.receive_json(timeout=2) == {
            "type": "error", "data": {"message": "boom", "source": "test"}}


async def test_events_unsubscribe_on_close(client, engine):
    async with client.ws_connect("/api/events") as ws:
        await ws.receive_json(timeout=2)
        assert engine.events.subscriber_count == 1
    for _ in range(100):
        if engine.events.subscriber_count == 0:
            break
        await asyncio.sleep(0.01)
    assert engine.events.subscriber_count == 0


async def test_volume_rejects_huge_integer(client):
    resp = await client.post(
        "/api/playback/volume", data='{"level": 1' + "0" * 309 + "}",
        headers={"Content-Type": "application/json"})
    assert resp.status == 400


async def test_cast_rejects_nul_in_path(client):
    resp = await client.post("/api/cast", json={"path": "/tmp/a\u0000b.mkv"})
    assert resp.status == 400


async def test_browse_rejects_nul_in_path(client):
    resp = await client.get("/api/browse", params={"path": "/tmp/a\u0000b"})
    assert resp.status == 400


async def test_rejects_foreign_origin(client, orchestrator):
    resp = await client.post("/api/playback/toggle", headers={"Origin": "https://evil.example"})
    assert resp.status == 403
    assert ("toggle_pause",) not in orchestrator.calls


async def test_rejects_foreign_origin_websocket(client):
    with pytest.raises(WSServerHandshakeError) as exc:
        await client.ws_connect("/api/events", headers={"Origin": "https://evil.example"})
    assert exc.value.status == 403


async def test_rejects_foreign_host(client):
    resp = await client.get("/api/library", headers={"Host": "rebind.evil.example:8485"})
    assert resp.status == 403


async def test_allows_tailnet_host_and_origin(aiohttp_client, engine):
    client = await aiohttp_client(create_app(engine, TOKEN, extra_hosts=("box.example.ts.net",)))
    resp = await client.get("/api/state", headers={
        "Host": "box.example.ts.net:8443", "Origin": "https://box.example.ts.net:8443"})
    assert resp.status == 200


async def test_runner_cleanup_closes_event_sockets(engine):
    runner = web.AppRunner(create_app(engine, TOKEN))
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", 0).start()
    port = runner.addresses[0][1]
    async with ClientSession() as session:
        ws = await session.ws_connect(f"http://127.0.0.1:{port}/api/events")
        await ws.receive_json(timeout=2)
        await asyncio.wait_for(runner.cleanup(), timeout=5)
        await ws.close()


async def test_browse_entries_have_titles_and_positions(client, history, watch_dir):
    ep = make_video(watch_dir / "Show.S01E02.Second.mkv")
    wid = await history.record_play(str(ep), ep.name, "dev", "Living Room", 100.0)
    await history.force_update_position(wid, 12.0)
    make_video(watch_dir / "Sub" / "x.mkv")
    entries = await (await client.get("/api/browse", params={"path": str(watch_dir)})).json()
    by_name = {e["name"]: e for e in entries}
    assert by_name["Sub"] == {"path": str(watch_dir / "Sub"), "name": "Sub", "is_dir": True}
    assert by_name["Show.S01E02.Second.mkv"]["subtitle"] == "S01E02 · Second"
    assert by_name["Show.S01E02.Second.mkv"]["position"] == 12.0
    assert by_name["Movie.mkv"]["title"] == "Movie"
    assert by_name["Movie.mkv"]["position"] is None


async def start_playing(client, engine, path, headers=None):
    engine.select_device(LIVING_ROOM.id)
    resp = await client.post("/api/cast", json={"path": str(path)}, headers=headers)
    assert resp.status == 202
    await engine.cast_task


async def test_next_with_nothing_playing_is_409(client):
    resp = await client.post("/api/playback/next")
    assert (resp.status, await resp.json()) == (409, {"error": "Nothing is playing"})


async def test_next_without_next_episode_is_409(client, engine, video):
    await start_playing(client, engine, video)
    resp = await client.post("/api/playback/next")
    assert (resp.status, await resp.json()) == (409, {"error": "No next episode"})


async def test_next_casts_next_episode_from_the_start(client, engine, orchestrator, history, watch_dir):
    e1 = make_video(watch_dir / "Show.S01E01.mkv")
    e2 = make_video(watch_dir / "Show.S01E02.mkv")
    wid = await history.record_play(str(e2), e2.name, "dev", "Living Room", 100.0)
    await history.force_update_position(wid, 40.0)
    await start_playing(client, engine, e1)
    resp = await client.post("/api/playback/next")
    assert (resp.status, await resp.json()) == (202, {"status": "casting", "device": "Living Room"})
    await engine.cast_task
    assert ("cast_file", e2, LIVING_ROOM.id) in orchestrator.calls
    assert ("seek", 40.0) not in orchestrator.calls
    assert engine.state()["current"]["path"] == str(e2)


async def test_next_outside_watch_folders_needs_local_token(client, engine, tmp_path):
    e1 = make_video(tmp_path / "elsewhere" / "Show.S01E01.mkv")
    make_video(tmp_path / "elsewhere" / "Show.S01E02.mkv")
    await start_playing(client, engine, e1, headers=LOCAL)
    assert (await client.post("/api/playback/next")).status == 403
    assert (await client.post("/api/playback/next", headers=LOCAL)).status == 202
    await engine.cast_task


async def test_next_episode_deleted_is_404(client, engine, watch_dir):
    e1 = make_video(watch_dir / "Show.S01E01.mkv")
    e2 = make_video(watch_dir / "Show.S01E02.mkv")
    await start_playing(client, engine, e1)
    e2.unlink()
    resp = await client.post("/api/playback/next")
    assert (resp.status, await resp.json()) == (404, {"error": "File not found"})


async def test_static_files_served_without_cache(client):
    resp = await client.get("/static/index.html")
    assert resp.status == 200
    assert resp.headers["Cache-Control"] == "no-cache"
    assert (await client.get("/")).headers["Cache-Control"] == "no-cache"


async def test_manifest_served_as_manifest_json(client):
    resp = await client.get("/static/manifest.webmanifest")
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("application/manifest+json")
    assert (await client.get("/static/apple-touch-icon.png")).status == 200


async def test_poster_served(client, engine):
    (engine.posters_dir / "show.jpg").write_bytes(b"jpegbytes")
    resp = await client.get("/posters/show.jpg?v=1")
    assert resp.status == 200
    assert await resp.read() == b"jpegbytes"
    assert "immutable" in resp.headers["Cache-Control"]


@pytest.mark.parametrize("name", ["missing.jpg", "notes.txt", ".hidden.jpg", "..%2Fhistory.db"])
async def test_poster_rejects(client, engine, name):
    (engine.posters_dir / "notes.txt").write_bytes(b"x")
    (engine.posters_dir / ".hidden.jpg").write_bytes(b"x")
    assert (await client.get(f"/posters/{name}")).status == 404


async def test_poster_refuses_symlink_out_of_folder(client, engine, tmp_path):
    secret = tmp_path / "secret.jpg"
    secret.write_bytes(b"private")
    (engine.posters_dir / "link.jpg").symlink_to(secret)
    assert (await client.get("/posters/link.jpg")).status == 404


async def test_poster_traversal_with_image_extension(client, engine, tmp_path):
    (tmp_path / "x.jpg").write_bytes(b"outside")
    assert (await client.get("/posters/..%2Fx.jpg")).status == 404

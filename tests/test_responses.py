import itertools
import os

import anyio
import pytest

from starlette import status
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)


def test_text_response(test_client_factory):
    async def app(scope, receive, send):
        response = Response("hello, world", media_type="text/plain")
        await response(scope, receive, send)

    client = test_client_factory(app)
    response = client.get("/")
    assert response.text == "hello, world"


def test_bytes_response(test_client_factory):
    async def app(scope, receive, send):
        response = Response(b"xxxxx", media_type="image/png")
        await response(scope, receive, send)

    client = test_client_factory(app)
    response = client.get("/")
    assert response.content == b"xxxxx"


def test_json_none_response(test_client_factory):
    async def app(scope, receive, send):
        response = JSONResponse(None)
        await response(scope, receive, send)

    client = test_client_factory(app)
    response = client.get("/")
    assert response.json() is None


def test_redirect_response(test_client_factory):
    async def app(scope, receive, send):
        if scope["path"] == "/":
            response = Response("hello, world", media_type="text/plain")
        else:
            response = RedirectResponse("/")
        await response(scope, receive, send)

    client = test_client_factory(app)
    response = client.get("/redirect")
    assert response.text == "hello, world"
    assert response.url == "http://testserver/"


def test_quoting_redirect_response(test_client_factory):
    async def app(scope, receive, send):
        if scope["path"] == "/I ♥ Starlette/":
            response = Response("hello, world", media_type="text/plain")
        else:
            response = RedirectResponse("/I ♥ Starlette/")
        await response(scope, receive, send)

    client = test_client_factory(app)
    response = client.get("/redirect")
    assert response.text == "hello, world"
    assert response.url == "http://testserver/I%20%E2%99%A5%20Starlette/"


def test_streaming_response(test_client_factory):
    filled_by_bg_task = ""

    async def app(scope, receive, send):
        async def numbers(minimum, maximum):
            for i in range(minimum, maximum + 1):
                yield str(i)
                if i != maximum:
                    yield ", "
                await anyio.sleep(0)

        async def numbers_for_cleanup(start=1, stop=5):
            nonlocal filled_by_bg_task
            async for thing in numbers(start, stop):
                filled_by_bg_task = filled_by_bg_task + thing

        cleanup_task = BackgroundTask(numbers_for_cleanup, start=6, stop=9)
        generator = numbers(1, 5)
        response = StreamingResponse(
            generator, media_type="text/plain", background=cleanup_task
        )
        await response(scope, receive, send)

    assert filled_by_bg_task == ""
    client = test_client_factory(app)
    response = client.get("/")
    assert response.text == "1, 2, 3, 4, 5"
    assert filled_by_bg_task == "6, 7, 8, 9"


def test_streaming_response_custom_iterator(test_client_factory):
    async def app(scope, receive, send):
        class CustomAsyncIterator:
            def __init__(self):
                self._called = 0

            def __aiter__(self):
                return self

            async def __anext__(self):
                if self._called == 5:
                    raise StopAsyncIteration()
                self._called += 1
                return str(self._called)

        response = StreamingResponse(CustomAsyncIterator(), media_type="text/plain")
        await response(scope, receive, send)

    client = test_client_factory(app)
    response = client.get("/")
    assert response.text == "12345"


def test_streaming_response_custom_iterable(test_client_factory):
    async def app(scope, receive, send):
        class CustomAsyncIterable:
            async def __aiter__(self):
                for i in range(5):
                    yield str(i + 1)

        response = StreamingResponse(CustomAsyncIterable(), media_type="text/plain")
        await response(scope, receive, send)

    client = test_client_factory(app)
    response = client.get("/")
    assert response.text == "12345"


def test_sync_streaming_response(test_client_factory):
    async def app(scope, receive, send):
        def numbers(minimum, maximum):
            for i in range(minimum, maximum + 1):
                yield str(i)
                if i != maximum:
                    yield ", "

        generator = numbers(1, 5)
        response = StreamingResponse(generator, media_type="text/plain")
        await response(scope, receive, send)

    client = test_client_factory(app)
    response = client.get("/")
    assert response.text == "1, 2, 3, 4, 5"


def test_response_headers(test_client_factory):
    async def app(scope, receive, send):
        headers = {"x-header-1": "123", "x-header-2": "456"}
        response = Response("hello, world", media_type="text/plain", headers=headers)
        response.headers["x-header-2"] = "789"
        await response(scope, receive, send)

    client = test_client_factory(app)
    response = client.get("/")
    assert response.headers["x-header-1"] == "123"
    assert response.headers["x-header-2"] == "789"


def test_response_phrase(test_client_factory):
    app = Response(status_code=204)
    client = test_client_factory(app)
    response = client.get("/")
    assert response.reason == "No Content"

    app = Response(b"", status_code=123)
    client = test_client_factory(app)
    response = client.get("/")
    assert response.reason == ""


def test_file_response(tmpdir, test_client_factory):
    path = os.path.join(tmpdir, "xyz")
    content = b"<file content>" * 1000
    with open(path, "wb") as file:
        file.write(content)

    filled_by_bg_task = ""

    async def numbers(minimum, maximum):
        for i in range(minimum, maximum + 1):
            yield str(i)
            if i != maximum:
                yield ", "
            await anyio.sleep(0)

    async def numbers_for_cleanup(start=1, stop=5):
        nonlocal filled_by_bg_task
        async for thing in numbers(start, stop):
            filled_by_bg_task = filled_by_bg_task + thing

    cleanup_task = BackgroundTask(numbers_for_cleanup, start=6, stop=9)

    async def app(scope, receive, send):
        response = FileResponse(
            path=path, filename="example.png", background=cleanup_task
        )
        await response(scope, receive, send)

    assert filled_by_bg_task == ""
    client = test_client_factory(app)
    response = client.get("/")
    expected_disposition = 'attachment; filename="example.png"'
    assert response.status_code == status.HTTP_200_OK
    assert response.content == content
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"] == expected_disposition
    assert "content-length" in response.headers
    assert "last-modified" in response.headers
    assert "etag" in response.headers
    assert filled_by_bg_task == "6, 7, 8, 9"


def test_file_response_with_directory_raises_error(tmpdir, test_client_factory):
    app = FileResponse(path=tmpdir, filename="example.png")
    client = test_client_factory(app)
    with pytest.raises(RuntimeError) as exc_info:
        client.get("/")
    assert "is not a file" in str(exc_info.value)


def test_file_response_with_missing_file_raises_error(tmpdir, test_client_factory):
    path = os.path.join(tmpdir, "404.txt")
    app = FileResponse(path=path, filename="404.txt")
    client = test_client_factory(app)
    with pytest.raises(RuntimeError) as exc_info:
        client.get("/")
    assert "does not exist" in str(exc_info.value)


def test_file_response_with_chinese_filename(tmpdir, test_client_factory):
    content = b"file content"
    filename = "你好.txt"  # probably "Hello.txt" in Chinese
    path = os.path.join(tmpdir, filename)
    with open(path, "wb") as f:
        f.write(content)
    app = FileResponse(path=path, filename=filename)
    client = test_client_factory(app)
    response = client.get("/")
    expected_disposition = "attachment; filename*=utf-8''%E4%BD%A0%E5%A5%BD.txt"
    assert response.status_code == status.HTTP_200_OK
    assert response.content == content
    assert response.headers["content-disposition"] == expected_disposition


def test_set_cookie(test_client_factory):
    async def app(scope, receive, send):
        response = Response("Hello, world!", media_type="text/plain")
        response.set_cookie(
            "mycookie",
            "myvalue",
            max_age=10,
            expires=10,
            path="/",
            domain="localhost",
            secure=True,
            httponly=True,
            samesite="none",
        )
        await response(scope, receive, send)

    client = test_client_factory(app)
    response = client.get("/")
    assert response.text == "Hello, world!"


def test_delete_cookie(test_client_factory):
    async def app(scope, receive, send):
        request = Request(scope, receive)
        response = Response("Hello, world!", media_type="text/plain")
        if request.cookies.get("mycookie"):
            response.delete_cookie("mycookie")
        else:
            response.set_cookie("mycookie", "myvalue")
        await response(scope, receive, send)

    client = test_client_factory(app)
    response = client.get("/")
    assert response.cookies["mycookie"]
    response = client.get("/")
    assert not response.cookies.get("mycookie")


def test_populate_headers(test_client_factory):
    app = Response(content="hi", headers={}, media_type="text/html")
    client = test_client_factory(app)
    response = client.get("/")
    assert response.text == "hi"
    assert response.headers["content-length"] == "2"
    assert response.headers["content-type"] == "text/html; charset=utf-8"


def test_head_method(test_client_factory):
    app = Response("hello, world", media_type="text/plain")
    client = test_client_factory(app)
    response = client.head("/")
    assert response.text == ""


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response_cls, status_code",
    list(itertools.product(*[[Response, JSONResponse], [100, 101, 102]])),
)
async def test_response_1xx(response_cls, status_code):
    scope = {}

    async def receive():
        return {}

    async def send(message: dict):
        if message["type"] == "http.response.start":
            # also ensures that self.raw_headers is not None
            assert len(message["headers"]) == 0
        elif message["type"] == "http.response.body":
            # per ASGI, if body key is missing, default is False
            assert "body" not in message or message["body"] == b""
            assert "more_body" not in message or message["more_body"] is False
        else:
            pass

    response = response_cls(status_code=status_code)
    await response.__call__(scope, receive, send)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response_cls, content",
    itertools.product(*[[Response, JSONResponse], [None, "test"]]),
)
async def test_response_204(response_cls, content):
    scope = {}

    async def receive():
        return {}

    async def send(message: dict):
        if message["type"] == "http.response.start":
            header_map = dict(message["headers"])
            assert b"content-length" not in header_map
            assert b"content-type" not in header_map
        elif message["type"] == "http.response.body":
            # per ASGI, if body key is missing, default is False
            assert "body" not in message or message["body"] == b""
            assert "more_body" not in message or message["more_body"] is False
        else:
            pass

    response = response_cls(status_code=204, content=content)
    await response.__call__(scope, receive, send)


@pytest.mark.anyio
@pytest.mark.parametrize("response_cls", [Response, JSONResponse])
async def test_response_205_with_te_header(response_cls):
    scope = {}

    async def receive():
        return {}

    async def send(message: dict):
        if message["type"] == "http.response.start":
            header_map = dict(message["headers"])
            assert header_map[b"transfer-encoding"] == b"chunked"
            assert b"content-length" not in header_map
            assert b"content-type" not in header_map
        elif message["type"] == "http.response.body":
            # per ASGI, if body key is missing, default is False
            assert "body" not in message or message["body"] == b""
            assert "more_body" not in message or message["more_body"] is False
        else:
            pass

    response = response_cls(status_code=205, headers={"transfer-encoding": "chunked"})
    await response.__call__(scope, receive, send)


@pytest.mark.anyio
@pytest.mark.parametrize("response_cls", [Response, JSONResponse])
async def test_response_205_with_cl_header(response_cls):
    scope = {}

    async def receive():
        return {}

    async def send(message: dict):
        if message["type"] == "http.response.start":
            header_map = dict(message["headers"])
            assert header_map[b"content-length"] == b"0"
            assert b"content-type" not in header_map
        elif message["type"] == "http.response.body":
            # per ASGI, if body key is missing, default is False
            assert "body" not in message or message["body"] == b""
            assert "more_body" not in message or message["more_body"] is False
        else:
            pass

    response = response_cls(status_code=205)
    await response.__call__(scope, receive, send)


@pytest.mark.anyio
@pytest.mark.parametrize("response_cls", [Response, JSONResponse])
async def test_response_304(response_cls):
    scope = {}

    async def receive():
        return {}

    async def send(message: dict):
        if message["type"] == "http.response.start":
            pass
        elif message["type"] == "http.response.body":
            # per ASGI, 'body', 'more_body' are optional.
            assert "body" not in message or message["body"] == b""
            assert "more_body" not in message or message["more_body"] is False
        else:
            pass

    response = response_cls(status_code=304)
    await response.__call__(scope, receive, send)

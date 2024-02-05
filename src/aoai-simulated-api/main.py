import os
import requests
import vcr
from fastapi import FastAPI, Request, Response

api_key = os.getenv("AZURE_OPENAI_KEY")
api_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")

simulator_mode = os.getenv("SIMULATOR_MODE") or "replay"

if api_key is None:
    print("AZURE_OPENAI_KEY is not set", flush=True)
    exit(1)

if api_endpoint is None:
    print("AZURE_OPENAI_ENDPOINT is not set", flush=True)
    exit(1)

allowed_simulator_modes = ["replay", "record", "generate"]
if simulator_mode not in allowed_simulator_modes:
    print(f"SIMULATOR_MODE must be one of {allowed_simulator_modes}", flush=True)
    exit(1)

vcr_filtered_request_headers = [
    # ignore api-key and don't persist!
    "api-key",
    # ignore these headers to reduce noise
    "user-agent",
    "x-stainless-arch",
    "x-stainless-async",
    "x-stainless-lang",
    "x-stainless-os",
    "x-stainless-package-version",
    "x-stainless-runtime",
    "x-stainless-runtime-version",
    "connection",
    "Content-Length",
    "accept-encoding",
]

var_filtered_response_headers = [
    # TODO - which (if any) of these do we care about? Any that we want to include in the responses?
    "apim-request-id",
    "azureml-model-session",
    "x-accel-buffering",
    "x-content-type-options",
    "x-ms-client-request-id",
    "x-ms-region",
    "x-request-id",
    "Cache-Control",
    "Content-Length",
]


def before_record_response(response):
    print("before_record_response", response, flush=True)
    for header in var_filtered_response_headers:
        if response["headers"].get(header):
            del response["headers"][header]
    return response
    # response["headers"].clear()
    # return response


async def handle_with_vcr(request: Request, response: Response):
    # https://vcrpy.readthedocs.io/en/latest/usage.html#record-modes
    if simulator_mode == "record":
        # add new requests but replay existing ones - can delete the file to start over
        record_mode = "new_episodes"
    elif simulator_mode == "replay":
        # don't record new requests, only replay existing ones
        record_mode = "none"
    else:
        raise NotImplementedError("simulator mode not implemented: " + simulator_mode)

    my_vcr = vcr.VCR(
        before_record_response=before_record_response,
        filter_headers=vcr_filtered_request_headers,
        record_mode=record_mode,
        cassette_library_dir="cassettes",  # TODO: enable configuring this from an environment variable
    )
    # can use "test.json", serializer="json" for JSON cassettes
    # TODO: determine the cassette name from the request
    with my_vcr.use_cassette("test.yaml"):
        # create new HTTP request to api_endpoint. copy headers, body, etc from request
        url = api_endpoint
        if url.endswith("/"):
            url = url[:-1]
        url += request.url.path + "?" + request.url.query

        # Copy most headers, but override auth
        fwd_headers = {
            k: v
            for k, v in request.headers.items()
            if k not in ["host", "authorization"]
        }
        fwd_headers["api-key"] = api_key

        body = await request.body()

        fwd_response = requests.request(
            request.method,
            url,
            headers=fwd_headers,
            data=body,
        )

        # TODO - what customisation do we want to apply? Overriding tokens remaining etc?
        for k, v in fwd_response.headers.items():
            response.headers[k] = v
        return fwd_response.json()


app = FastAPI()


@app.get("/")
async def root():
    return {"message": "👋 aoai-simulated-api is running"}


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def catchall(request: Request, response: Response):
    print("⚠️ handling route: " + request.url.path, flush=True)

    if simulator_mode == "generate":
        raise NotImplementedError("generate mode not implemented")

    if simulator_mode == "record" or simulator_mode == "replay":
        return await handle_with_vcr(request, response)

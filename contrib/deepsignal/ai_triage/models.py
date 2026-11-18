"""Provider-pluggable HTTP model adapters."""
import json
import urllib.error
import urllib.parse
import urllib.request

from contrib.deepsignal.ai_guard import secrets


class HostNotAllowed(ValueError):
    pass


class UrlClient:
    def post(self, url, headers, body, timeout, proxy=None):
        handlers = []
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"https": proxy}))
        opener = urllib.request.build_opener(*handlers)
        request = urllib.request.Request(url, body.encode(), headers, method="POST")
        with opener.open(request, timeout=timeout) as response:
            return json.loads(response.read())


class ApiModel:
    def __init__(self, provider, url, model, key_env, client=None,
                 allowed_hosts=None, proxy=None, timeout=60, key_loader=None):
        self.provider = provider
        self.url = url
        self.model = model
        self.key_env = key_env
        self.client = client or UrlClient()
        self.allowed_hosts = set(allowed_hosts or ())
        self.proxy = proxy
        self.timeout = timeout
        self.key_loader = key_loader or secrets.load_key

    def complete(self, pack, max_output_tokens=1000):
        host = urllib.parse.urlparse(self.url).hostname
        if host not in self.allowed_hosts:
            raise HostNotAllowed("api.allowed_hosts does not allow %s" % host)
        key = self.key_loader(self.key_env)
        headers = {"Content-Type": "application/json"}
        content = json.dumps(pack, sort_keys=True)
        if self.provider == "anthropic":
            headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
            request = {"model": self.model, "max_tokens": max_output_tokens,
                       "messages": [{"role": "user", "content": content}]}
        else:
            headers["Authorization"] = "Bearer " + key
            request = {"model": self.model, "max_tokens": max_output_tokens,
                       "messages": [{"role": "user", "content": content}]}
        response = self.client.post(self.url, headers, json.dumps(request),
                                    self.timeout, self.proxy)
        if self.provider == "anthropic":
            answer = response["content"][0]["text"]
        else:
            answer = response["choices"][0]["message"]["content"]
        return {"content": answer, "usage": response.get("usage", {})}


class LocalModel(ApiModel):
    def __init__(self, url, model, client=None, timeout=60):
        host = urllib.parse.urlparse(url).hostname
        super().__init__("openai", url, model, "local", client, [host],
                         timeout=timeout, key_loader=lambda unused: "local")

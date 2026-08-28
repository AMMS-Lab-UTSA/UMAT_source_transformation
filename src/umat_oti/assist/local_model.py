"""A thin client for a model running on this machine, and nothing more.

Local on purpose. A verification pipeline that reached a network service would
make its own behaviour depend on something outside the snapshot, and a result
that cannot be reproduced from the repository plus the pinned inputs is not
evidence. This talks to a server on the loopback interface or it reports that
it cannot.

Every caller must treat absence as normal. ``model_from_environment`` returns
``None`` when nothing is reachable, and the deterministic path that existed
before any of this has to still be the one that produces the answer.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

__all__ = ["LocalModel", "ModelUnavailable", "model_from_environment"]

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5-coder:7b"

#: Environment overrides, so a different box can point at a different model
#: without editing anything.
HOST_VARIABLE = "UMAT_OTI_LOCAL_MODEL_HOST"
MODEL_VARIABLE = "UMAT_OTI_LOCAL_MODEL"


class ModelUnavailable(RuntimeError):
    """No local model could be reached. Always recoverable by not using one."""


@dataclass
class LocalModel:
    """A named model on a loopback server."""

    name: str = DEFAULT_MODEL
    host: str = DEFAULT_HOST
    timeout: int = 120

    def available(self) -> bool:
        try:
            self.tags()
        except ModelUnavailable:
            return False
        return True

    def tags(self) -> list[str]:
        payload = self._get("/api/tags")
        return [str(m.get("name", "")) for m in payload.get("models", [])]

    def ask(self, prompt: str, *, temperature: float = 0.0,
            max_tokens: int = 256) -> tuple[str, str]:
        """(answer, prompt digest).

        Temperature is zero by default and the digest of the prompt is
        returned with the answer, so a proposal can record exactly what was
        asked. It still is not reproducible in the way the rest of this
        repository is -- which is why a proposal is never a value.
        """
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        body = json.dumps({
            "model": self.name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{self.host}/api/generate", data=body,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as handle:
                payload = json.loads(handle.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise ModelUnavailable(f"{self.host} did not answer: {exc}") from exc
        return str(payload.get("response", "")).strip(), digest

    def _get(self, path: str) -> dict:
        try:
            with urllib.request.urlopen(f"{self.host}{path}",
                                        timeout=min(self.timeout, 10)) as handle:
                return json.loads(handle.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise ModelUnavailable(f"{self.host} is not reachable: {exc}") from exc


def model_from_environment() -> Optional[LocalModel]:
    """A reachable local model, or ``None``.

    ``None`` is an ordinary outcome, not an error: every caller has a
    deterministic path that does not need one.
    """
    model = LocalModel(
        name=os.environ.get(MODEL_VARIABLE, DEFAULT_MODEL),
        host=os.environ.get(HOST_VARIABLE, DEFAULT_HOST))
    if not model.available():
        return None
    if model.name not in model.tags():
        return None
    return model

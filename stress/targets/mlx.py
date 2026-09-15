"""MLX target — Apple-silicon local inference, permitted by the policy alongside Ollama.

Two modes:
  mlx:<model>              in-process via mlx_lm (pip install mlx-lm)
  mlx-server:<url>         an mlx_lm.server OpenAI-compatible endpoint (python -m mlx_lm.server)
"""
from __future__ import annotations


class MLX:
    def __init__(self, model: str):
        self.name, self.model = f"mlx:{model}", model
        self._m = self._t = None

    def _load(self):
        if self._m is None:
            from mlx_lm import load
            self._m, self._t = load(self.model)
        return self._m, self._t

    def ask(self, system: str, user: str) -> str:
        from mlx_lm import generate
        m, t = self._load()
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        prompt = (t.apply_chat_template(msgs, add_generation_prompt=True)
                  if getattr(t, "chat_template", None) else f"{system}\n\n{user}")
        return generate(m, t, prompt=prompt, max_tokens=512, verbose=False)

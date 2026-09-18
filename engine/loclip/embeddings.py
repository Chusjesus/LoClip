"""Modelo visual (SigLIP 2 vía open_clip): convierte imágenes y texto a vectores comparables.

SigLIP 2 es multilingüe: puedes buscar en español o en inglés sin traducir.
"""
from __future__ import annotations

import threading

import numpy as np
import torch
from PIL import Image

from .config import models_dir
from .hardware import VISUAL_MODELS


class VisualModel:
    def __init__(self, tier_or_name: str = "base", device: str = "auto"):
        import open_clip

        spec = VISUAL_MODELS.get(tier_or_name)
        if spec:
            self.name, pretrained, self.dim = spec["name"], spec["pretrained"], spec["dim"]
        else:
            self.name, pretrained, self.dim = tier_or_name, "webli", 0
        if device == "auto":
            if torch.cuda.is_available():
                device = "cuda"
            elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"
        self.device = device
        self.lock = threading.Lock()
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            self.name, pretrained=pretrained, cache_dir=str(models_dir()), device=device,
        )
        self.model.eval()
        self.tokenizer = open_clip.get_tokenizer(self.name, cache_dir=str(models_dir()))
        self.use_half = device == "cuda"
        if self.use_half:
            self.model.half()
        if not self.dim:
            with torch.no_grad():
                self.dim = int(self.model.encode_text(self.tokenizer(["x"]).to(device)).shape[-1])

    @torch.no_grad()
    def encode_images(self, images: list[Image.Image], batch_size: int = 32) -> np.ndarray:
        out = []
        for i in range(0, len(images), batch_size):
            batch = torch.stack([self.preprocess(im) for im in images[i:i + batch_size]]).to(self.device)
            if self.use_half:
                batch = batch.half()
            with self.lock:
                feats = self.model.encode_image(batch)
            feats = feats / feats.norm(dim=-1, keepdim=True)
            out.append(feats.float().cpu().numpy())
        return np.concatenate(out) if out else np.zeros((0, self.dim), dtype=np.float32)

    @torch.no_grad()
    def encode_text(self, texts: list[str]) -> np.ndarray:
        toks = self.tokenizer(texts).to(self.device)
        with self.lock:
            feats = self.model.encode_text(toks)
        feats = feats / feats.norm(dim=-1, keepdim=True)
        return feats.float().cpu().numpy()


def to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float16).tobytes()


def from_blob(blob: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float16).reshape(-1, dim).astype(np.float32)

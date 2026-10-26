"""Loader for the Mesolitica Malaysian embedding model (Zolkepli et al., 2024, arXiv:2402.03053).

The model on Hugging Face (mesolitica/llama2-embedding-600m-8k-contrastive) normally needs
`trust_remote_code=True`, which runs Python code downloaded from the internet. Instead, we
re-implement that code here (it is short) so nothing downloaded is executed: we only
download the weights. Logic copied from the repo's modeling_contrastive.py:

    hidden states of a small Llama model -> linear layer to 1536 dims
    -> mean over the tokens (ignoring padding) -> L2-normalise
"""

import numpy as np
import torch
from torch import nn
from transformers import AutoTokenizer, LlamaConfig, LlamaModel

MESOLITICA_ID = "mesolitica/llama2-embedding-600m-8k-contrastive"


class LlamaModelEmbedding(LlamaModel):
    """Same layer names as the original, so the downloaded weights load into it."""

    def __init__(self, config: LlamaConfig):
        super().__init__(config)
        self.dense_layer = nn.Linear(config.hidden_size, 1536)

    def encode(self, input_ids, attention_mask):
        hidden = super().forward(input_ids=input_ids, attention_mask=attention_mask,
                                 return_dict=True).last_hidden_state
        out = self.dense_layer(hidden)
        mask = attention_mask.unsqueeze(-1).float()
        mean = (out * mask).sum(dim=1) / mask.sum(dim=1)     # mean pooling (config: "mean")
        return nn.functional.normalize(mean, dim=-1)         # config: "normalized": true


class MesoliticaEncoder:
    """Small wrapper with the same .encode() call style as SentenceTransformer."""

    def __init__(self, model_id=MESOLITICA_ID):
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = LlamaModelEmbedding.from_pretrained(model_id, torch_dtype=torch.float32)
        self.model.eval()

    @torch.no_grad()
    def encode(self, texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False,
               convert_to_numpy=True):
        from tqdm.auto import tqdm
        out = []
        starts = range(0, len(texts), batch_size)
        for i in tqdm(starts, desc="Batches", disable=not show_progress_bar):
            batch = self.tokenizer(list(texts[i:i + batch_size]), return_tensors="pt", padding=True)
            out.append(self.model.encode(batch["input_ids"], batch["attention_mask"]).numpy())
        return np.vstack(out)   # already L2-normalised

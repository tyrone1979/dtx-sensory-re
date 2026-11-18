#!/bin/bash
source ~/anaconda3/etc/profile.d/conda.sh
conda activate re
# httpx2 与 huggingface_hub 冲突，改用 ModelScope 下载
pip install -q modelscope 2>&1 | tail -1
modelscope download --model Qwen/Qwen2.5-7B-Instruct --local_dir ~/models/Qwen2.5-7B-Instruct
echo "MODELSCOPE_DONE rc=$?"
ls -la ~/models/Qwen2.5-7B-Instruct | head -20

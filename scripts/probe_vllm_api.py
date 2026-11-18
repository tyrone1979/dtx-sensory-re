import dataclasses
import inspect

from vllm import SamplingParams

print("annotations:", [k for k in getattr(SamplingParams, "__annotations__", {})][:60])
try:
    flds = [f.name for f in dataclasses.fields(SamplingParams)]
    print("dataclass fields:", flds)
except Exception as e:
    print("not dataclass:", e)
print("init params:", list(inspect.signature(SamplingParams.__init__).parameters))

try:
    from vllm.sampling_params import StructuredOutputsParams
    print("SOP dir:", [a for a in dir(StructuredOutputsParams) if not a.startswith("_")])
except Exception as e:
    print("import err:", e)

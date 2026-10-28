# V0.2.3 identity audit (before migration)

## Classification

- A — Migrate: node categories/display branding, frontend extension names and
  timing installation symbol, private direct-import namespace, test package
  namespace, installation instructions, User-Agent and log prefixes.
- B — Preserve contracts: all six node class/type IDs (including GH suffixes),
  MiniMax/GHVideoRequest types, state keys, tag schemes, input IDs, output order,
  model_variant values, upload-cache directory `goohai_minimax_h3_fal`, and
  `/goohai/minimax-h3/prompt-optimizer/*` compatibility HTTP endpoints.
- C — Historical attribution: existing GitHub/account URLs are real source and
  author links, not invented HuTX repository URLs. Old workflow fixture titles
  and this pre-migration scan remain historical evidence.

## Findings

- No hardcoded `/extensions/Goohai-MiniMax-H3_Integration/` resource URL was found.
- `WEB_DIRECTORY = "./web"`; sibling modules use relative imports. ComfyUI
  `/scripts/app.js` and `/scripts/api.js` are host APIs, not plugin resources.
- Completion audio uses `new URL("../audio/done.mp3", import.meta.url)`.
- Optimizer route ownership is `prompt_optimizer/legacy.py`, reached through
  `prompt_optimizer/__init__.py`. The older root `prompt_optimizer.py` remains
  archival compatibility source; normal package resolution selects the package.
- Browser locale reads use ComfyUI/global locale keys, not a Goohai storage key.
- Persisted `gh_h3_state`, `gh_cloud_video_state`, `gh_state_json`,
  `gh_cloud_state_json` and timing/request identifiers retain their contracts.
- Both development and installed old directories were ordinary directories,
  not junctions. Never install both old and new identities together.

## Full pre-migration text matches

```text
.\cloud_video_nodes.py:10:NODE_CATEGORY = "Goohai/Cloud Video"
.\fal_nodes.py:13:NODE_CATEGORY = "Goohai/MiniMax H3 Integration"
.\__init__.py:16:    _package_name = "_goohai_minimax_h3_integration_direct"
.\fal_media.py:203:    return root / "goohai_minimax_h3_fal"
.\prompt_optimizer.py:598:            headers={"User-Agent": "Goohai-MiniMax-H3-Integration"},
.\prompt_optimizer.py:1745:    routes.get("/goohai/minimax-h3/prompt-optimizer/config")(get_prompt_optimizer_config)
.\prompt_optimizer.py:1746:    routes.get("/goohai/minimax-h3/prompt-optimizer/models")(list_prompt_optimizer_models)
.\prompt_optimizer.py:1747:    routes.get("/goohai/minimax-h3/prompt-optimizer/runninghub-models")(refresh_runninghub_models)
.\prompt_optimizer.py:1748:    routes.post("/goohai/minimax-h3/prompt-optimizer/config")(save_prompt_optimizer_config)
.\prompt_optimizer.py:1749:    routes.post("/goohai/minimax-h3/prompt-optimizer/optimize")(optimize_prompt)
.\prompt_optimizer.py:1750:    routes.post("/goohai/minimax-h3/prompt-optimizer/start")(start_prompt_optimization)
.\prompt_optimizer.py:1751:    routes.get("/goohai/minimax-h3/prompt-optimizer/status")(prompt_optimization_status)
.\prompt_optimizer.py:1752:    routes.post("/goohai/minimax-h3/prompt-optimizer/cancel")(cancel_prompt_optimization)
.\nodes.py:37:NODE_CATEGORY = "Goohai/MiniMax H3 Integration"
.\web\js\prompt_optimizer_shared.js:1:const OPTIMIZER_ROUTE = "/goohai/minimax-h3/prompt-optimizer";
.\web\js\minimax_h3_integration.js:23:const OPTIMIZER_ROUTE = "/goohai/minimax-h3/prompt-optimizer";
.\web\js\minimax_h3_integration.js:3281:    name: "goohai.minimax_h3_integration",
.\locales\zh\main.json:3:    "Goohai/MiniMax H3 Integration": "Goohai/MiniMax H3 集成"
.\web\js\gh_cloud_video_input.js:434:    name: "goohai.gh_cloud_video_input",
.\web\js\fal_h3_max_timing.js:6:const INSTALL_MARK = Symbol.for("goohai.falH3MaxTiming.installed");
.\web\js\fal_h3_max_timing.js:83:    name: "Goohai.FalH3MaxTiming",
.\prompt_optimizer\legacy.py:598:            headers={"User-Agent": "Goohai-MiniMax-H3-Integration"},
.\prompt_optimizer\legacy.py:1821:    routes.get("/goohai/minimax-h3/prompt-optimizer/config")(get_prompt_optimizer_config)
.\prompt_optimizer\legacy.py:1822:    routes.get("/goohai/minimax-h3/prompt-optimizer/models")(list_prompt_optimizer_models)
.\prompt_optimizer\legacy.py:1823:    routes.get("/goohai/minimax-h3/prompt-optimizer/runninghub-models")(refresh_runninghub_models)
.\prompt_optimizer\legacy.py:1824:    routes.post("/goohai/minimax-h3/prompt-optimizer/config")(save_prompt_optimizer_config)
.\prompt_optimizer\legacy.py:1825:    routes.post("/goohai/minimax-h3/prompt-optimizer/secret")(store_prompt_optimizer_secret)
.\prompt_optimizer\legacy.py:1826:    routes.post("/goohai/minimax-h3/prompt-optimizer/optimize")(optimize_prompt)
.\prompt_optimizer\legacy.py:1827:    routes.post("/goohai/minimax-h3/prompt-optimizer/start")(start_prompt_optimization)
.\prompt_optimizer\legacy.py:1828:    routes.get("/goohai/minimax-h3/prompt-optimizer/status")(prompt_optimization_status)
.\prompt_optimizer\legacy.py:1829:    routes.post("/goohai/minimax-h3/prompt-optimizer/cancel")(cancel_prompt_optimization)
.\web\js\fal_h3_max_model_variant.js:43:    name: "Goohai.FalH3MaxModelVariant",
.\locales\en\main.json:3:    "Goohai/MiniMax H3 Integration": "Goohai/MiniMax H3 Integration"
.\README.md:2:<a href="https://github.com/goohai/Goohai-MiniMax-H3_Integration" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/GitHub-MiniMax--H3%20Integration-1E90FF?style=flat-square" alt="GitHub" /></a>
.\README.md:3:<a href="https://github.com/goohai/Goohaitools-comfyui" target="_blank" rel="noopener noreferrer"><img src="https://img.shields.io/badge/GitHub-Goohaitools--comfyui-1E90FF?style=flat-square" alt="Goohaitools-comfyui" /></a>
.\README.md:240:git clone https://github.com/goohai/Goohai-MiniMax-H3_Integration.git
.\README.md:246:python -m pip install -r ComfyUI/custom_nodes/Goohai-MiniMax-H3_Integration/requirements.txt
.\README.md:252:..\python\python.exe -m pip install -r .\custom_nodes\Goohai-MiniMax-H3_Integration\requirements.txt
.\tests\test_prompt_optimizer_security_contract.py:11:from goohai_minimax_h3_testpkg.fal_router import build_fal_plan
.\tests\test_prompt_optimizer_security_contract.py:12:from goohai_minimax_h3_testpkg.gh_video_request import (
.\tests\test_prompt_optimizer_security_contract.py:16:from goohai_minimax_h3_testpkg.prompt_optimizer.engine import optimizer_report
.\tests\test_prompt_optimizer_security_contract.py:17:from goohai_minimax_h3_testpkg.prompt_optimizer.secrets import (
.\tests\test_prompt_optimizer_security_contract.py:23:from goohai_minimax_h3_testpkg.prompt_optimizer.template_manager import (
.\tests\test_prompt_optimizer_security_contract.py:96:    from goohai_minimax_h3_testpkg.prompt_optimizer.config_schema import (
.\tests\test_prompt_optimizer_security_contract.py:100:    module_name = "goohai_minimax_h3_testpkg.prompt_optimizer.legacy"
.\tests\test_prompt_optimizer_cloud.py:14:from goohai_minimax_h3_testpkg.prompt_optimizer import engine
.\tests\test_prompt_optimizer_cloud.py:15:from goohai_minimax_h3_testpkg.prompt_optimizer.config_schema import public_optimizer_config
.\tests\test_prompt_optimizer_cloud.py:16:from goohai_minimax_h3_testpkg.prompt_optimizer.template_manager import (
.\tests\test_prompt_optimizer_cloud.py:29:    module_name = "goohai_minimax_h3_testpkg.prompt_optimizer.legacy"
.\tests\test_prompt_optimizer_cloud.py:157:    module_name = "goohai_minimax_h3_testpkg.cloud_video_nodes"
.\tests\test_optimizer_persistence.py:17:from goohai_minimax_h3_testpkg.prompt_optimizer import config_schema as schema
.\tests\test_optimizer_persistence.py:18:from goohai_minimax_h3_testpkg.fal_models import FalValidationError
.\tests\test_optimizer_persistence.py:19:from goohai_minimax_h3_testpkg.gh_video_request import (
.\tests\test_optimizer_persistence.py:23:from goohai_minimax_h3_testpkg import fal_h3_max
.\tests\test_optimizer_persistence.py:37:    namespace = {"__package__": "goohai_minimax_h3_testpkg.prompt_optimizer"}
.\tests\test_optimizer_persistence.py:49:    fake_legacy = types.ModuleType("goohai_minimax_h3_testpkg.prompt_optimizer.legacy")
.\tests\test_optimizer_persistence.py:246:    name = "goohai_minimax_h3_testpkg.cloud_video_nodes"
.\tests\test_legacy_workflow_compatibility.py:9:from goohai_minimax_h3_testpkg.fal_models import (
.\tests\test_legacy_workflow_compatibility.py:13:from goohai_minimax_h3_testpkg.fal_router import build_fal_plan
.\tests\test_legacy_workflow_compatibility.py:14:from goohai_minimax_h3_testpkg.gh_video_request import normalize_video_request
.\tests\test_gh_video_request.py:8:from goohai_minimax_h3_testpkg.fal_models import FalValidationError
.\tests\test_gh_video_request.py:9:from goohai_minimax_h3_testpkg.gh_video_request import (
.\tests\test_fal_turbo.py:16:from goohai_minimax_h3_testpkg import fal_h3_max, fal_media
.\tests\test_fal_turbo.py:17:from goohai_minimax_h3_testpkg.fal_api_client import FalQueueResult
.\tests\test_fal_turbo.py:18:from goohai_minimax_h3_testpkg.fal_h3_max import FalH3MaxService
.\tests\test_fal_turbo.py:19:from goohai_minimax_h3_testpkg.fal_media import FalUploadCache, InspectedMedia, MediaInspection
.\tests\test_fal_turbo.py:20:from goohai_minimax_h3_testpkg.fal_models import (
.\tests\test_fal_turbo.py:28:from goohai_minimax_h3_testpkg.fal_router import build_fal_plan
.\tests\test_fal_turbo.py:29:from goohai_minimax_h3_testpkg.gh_video_request import (
.\tests\test_fal_turbo.py:178:    module_name = "goohai_minimax_h3_testpkg.cloud_video_nodes"
.\tests\test_fal_turbo.py:289:    module_name = "goohai_minimax_h3_testpkg.fal_nodes"
.\tests\test_fal_turbo.py:308:    from goohai_minimax_h3_testpkg.fal_models import FalGenerationResult
.\tests\test_fal_router.py:11:from goohai_minimax_h3_testpkg import fal_h3_max
.\tests\test_fal_router.py:12:from goohai_minimax_h3_testpkg.fal_api_client import (
.\tests\test_fal_router.py:17:from goohai_minimax_h3_testpkg.fal_h3_max import FalH3MaxService
.\tests\test_fal_router.py:18:from goohai_minimax_h3_testpkg.fal_media import InspectedMedia, MediaInspection
.\tests\test_fal_router.py:19:from goohai_minimax_h3_testpkg.fal_models import FalMediaUrls, FalValidationError
.\tests\test_fal_router.py:20:from goohai_minimax_h3_testpkg.gh_video_request import (
.\tests\test_fal_router.py:24:from goohai_minimax_h3_testpkg.fal_router import (
.\tests\test_fal_router.py:222:    module = importlib.import_module("goohai_minimax_h3_testpkg.fal_api_client")
.\tests\test_fal_router.py:230:    module = importlib.import_module("goohai_minimax_h3_testpkg.fal_api_client")
.\tests\test_fal_router.py:243:    module = importlib.import_module("goohai_minimax_h3_testpkg.fal_api_client")
.\tests\test_fal_prompt_mapping.py:5:from goohai_minimax_h3_testpkg.fal_models import FalValidationError
.\tests\test_fal_prompt_mapping.py:6:from goohai_minimax_h3_testpkg.fal_router import adapt_prompt_for_fal
.\tests\test_fal_prompt_mapping.py:7:from goohai_minimax_h3_testpkg.gh_video_request import (
.\tests\test_fal_media.py:12:from goohai_minimax_h3_testpkg import fal_media
.\tests\test_fal_media.py:13:from goohai_minimax_h3_testpkg.fal_media import (
.\tests\test_fal_media.py:21:from goohai_minimax_h3_testpkg.fal_models import FalValidationError
.\tests\test_fal_media.py:22:from goohai_minimax_h3_testpkg.gh_video_request import (
.\tests\conftest.py:8:PACKAGE_NAME = "goohai_minimax_h3_testpkg"
.\tests\test_fal_cost.py:8:from goohai_minimax_h3_testpkg import fal_h3_max
.\tests\test_fal_cost.py:9:from goohai_minimax_h3_testpkg.fal_h3_max import FalH3MaxService
.\tests\test_fal_cost.py:10:from goohai_minimax_h3_testpkg.fal_media import InspectedMedia, MediaInspection
.\tests\test_fal_cost.py:11:from goohai_minimax_h3_testpkg.fal_models import (
.\tests\test_fal_cost.py:15:from goohai_minimax_h3_testpkg.fal_router import (
.\tests\test_fal_cost.py:20:from goohai_minimax_h3_testpkg.gh_video_request import (
.\tests\test_fal_manifest.py:5:from goohai_minimax_h3_testpkg.fal_models import build_source_manifest
.\tests\test_cloud_fal_router.py:5:from goohai_minimax_h3_testpkg.fal_h3_max import FalH3MaxService
.\tests\test_cloud_fal_router.py:6:from goohai_minimax_h3_testpkg.fal_models import FalValidationError
.\tests\test_cloud_fal_router.py:7:from goohai_minimax_h3_testpkg.fal_router import (
.\tests\test_cloud_fal_router.py:14:from goohai_minimax_h3_testpkg.gh_video_request import (
.\tests\test_cloud_fal_router.py:143:    from goohai_minimax_h3_testpkg import fal_h3_max
.\tests\test_cloud_node_isolation.py:11:PACKAGE = "goohai_minimax_h3_testpkg"
.\tests\test_cloud_state_validation.py:14:from goohai_minimax_h3_testpkg import fal_h3_max
.\tests\test_cloud_state_validation.py:15:from goohai_minimax_h3_testpkg.fal_models import FalValidationError
.\tests\test_cloud_state_validation.py:16:from goohai_minimax_h3_testpkg.gh_video_request import (
.\tests\test_cloud_state_validation.py:65:    name = "goohai_minimax_h3_testpkg.cloud_video_nodes"
.\tests\test_fal_download_fallback.py:6:from goohai_minimax_h3_testpkg import fal_h3_max
.\tests\test_fal_download_fallback.py:7:from goohai_minimax_h3_testpkg.fal_api_client import FalQueueResult
.\tests\test_fal_download_fallback.py:8:from goohai_minimax_h3_testpkg.fal_h3_max import FalH3MaxService
.\tests\test_fal_download_fallback.py:9:from goohai_minimax_h3_testpkg.gh_video_request import normalize_video_request
```

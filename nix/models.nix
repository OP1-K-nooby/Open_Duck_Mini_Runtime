# The upstream RL walk policies, pinned to a static apirrone/Open_Duck_Mini
# revision for reproducibility. Both were published together (upstream commit
# 981750b) as alternatives; the README links BEST_WALK_ONNX_2 as the latest.
{ fetchurl }:
let
  rev = "b23317a485b3cec7d8417f352478778b3475173c";
  fetchModel = name: hash: fetchurl {
    inherit name hash;
    url = "https://raw.githubusercontent.com/apirrone/Open_Duck_Mini/${rev}/${name}";
  };
in
{
  best-walk = fetchModel "BEST_WALK_ONNX.onnx"
    "sha256-y2FFOovLVHzP3rTwO6D6Z+vPdn3PSqblyaDZKzAvmyM=";
  best-walk-2 = fetchModel "BEST_WALK_ONNX_2.onnx"
    "sha256-PGBvk4GhcQzI/s23RCeH3L/OPum8AqbxIkd0qys6EGc=";
}

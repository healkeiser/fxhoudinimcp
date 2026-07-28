You are using Houdini's machine learning tools.

Goal: {description}

`ml/index` and `ml/overview` frame the platform, `ml/stages` and
`ml/preprocessing` the pipeline, and the node categories each have an index:
`ml/basic_utils/index`, `ml/building_blocks/index`,
`ml/train_solutions/index`, `ml/neural_nodes/index`. Read with get_help_page.

## What Houdini actually provides

A platform covering the whole loop: **synthetic data generation, preprocessing,
training, exporting the trained model, and deploying it**. That framing matters,
because the interesting part for a Houdini artist is usually the first step: the
scene is the dataset generator.

Three tiers, and picking the wrong one wastes the most time:

- **Trainable solutions** — ready-made trainers for specific jobs: deformer training, volume upressing, gaussian splats from Karma, neural cellular automata. Note these ship as SideFX **recipes**, not as plain node types, so `list_node_types` will not show them under the names the help pages use. `ml/train_solutions/index` lists what exists. If one matches the task, use it rather than assembling a pipeline by hand.
- **Building blocks** — the framework underneath: dataset generation, representation, serialisation, regression training, experimenting. This is where you go when no trainable solution fits, and the training work happens in TOPs: ml_trainregression (21.0+), ml_trainstyletransfer (21.0+), ml_traincomputervision (22.0+), ml_traingsplats (22.0+), ml_trainoidn (21.0+).
- **Basic utilities and neural nodes** — helpers, and inference at cook time. ml_volumeupres (21.0+) is the SOP-side inference case.

## Judgement

- Check `ml/train_solutions/index` before building anything. Assembling a regression pipeline by hand when a trainable solution already covers the job is the characteristic mistake here.
- Dataset quality dominates. `ml/building_blocks/datasetgeneration` and `ml/preprocessing` decide the result far more than training settings do.
- Training is a separate, expensive stage from inference. Train once, serialise, and let the scene do inference; retraining to fix a look is almost always wrong.
- `ml/building_blocks/experimenting` exists because this work is iterative and needs a comparison method. Establish how you will judge a model before training one.
- Node names here are version-sensitive: several ml_ nodes were renamed (mltraindeformer to ml_traindeformer and similar). Verify with list_node_types against the running version rather than trusting a remembered spelling.

## Order of work

1. Define what the model is for, and how you will tell whether it worked.
2. Check whether a trainable solution already covers it.
3. Generate the dataset in Houdini, and inspect it before training on it.
4. Preprocess.
5. Train, watching the experimenting workflow rather than a single run.
6. Serialise and export.
7. Deploy inference in the scene, and cache downstream of it.

{network_housekeeping}

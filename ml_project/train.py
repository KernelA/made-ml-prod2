import os
import json
import logging

import hydra
from hydra.core.config_store import ConfigStore
from sklearn import compose, pipeline
from sklearn import model_selection, metrics
import pandas as pd

from heat_diss.preprocessing import feature_target_split, clean_data
from config import CrossValConfig, \
    FeatureTransformerConfig, TrainConfig, \
    LogisticRegressionConfig, SVCConfig
from utils import get_class_type, dump_pickle

LOGGER = logging.getLogger()


cs = ConfigStore().instance()
cs.store(group="cls_config", name="svc", node=SVCConfig)
cs.store(group="cls_config", name="log_reg", node=LogisticRegressionConfig)
cs.store(name="feature_transform", node=FeatureTransformerConfig)
cs.store(name="cross_val", node=CrossValConfig)
cs.store(name="train", node=TrainConfig)


def prepare_date(data: pd.DataFrame, uniq_values_limit: int, target_variable: str):
    data = clean_data(data, uniq_values_limit)
    return feature_target_split(data, target_variable)


def cross_val(cls_pipeline, data: pd.DataFrame, cfg: TrainConfig):
    features, target = prepare_date(data,
                                    cfg.data_config.unique_values_limit,
                                    cfg.data_config.target_variable)

    cross_val_score = model_selection.cross_validate(cls_pipeline, features, target,
                                                     scoring=list(cfg.cross_val.scores),
                                                     cv=cfg.cross_val.cv)

    val_score = pd.DataFrame(cross_val_score)
    LOGGER.info("Cross validation results:\n%s", val_score)


@hydra.main(config_name="train")
def train(cfg: TrainConfig):
    column_transformers = compose.ColumnTransformer([(transform.stage_name,
                                                      get_class_type(transform.classname)(**transform.params), pd.Index(transform.columns))
                                                     for transform in cfg.feature_transform.transformers], remainder="drop")
    cls_params = dict(cfg.cls_config)
    cls_params.pop("classname")
    cls = get_class_type(cfg.cls_config.classname)(**cls_params)

    cls_pipeline = pipeline.Pipeline([
        ("feature_transform", column_transformers),
        ("cls", cls)
    ])

    train_path = os.path.join(hydra.utils.get_original_cwd(), cfg.data_config.path_to_train)
    train_data = pd.read_csv(train_path)

    test_path = os.path.join(hydra.utils.get_original_cwd(), cfg.data_config.path_to_test)
    test_data = pd.read_csv(test_path)

    LOGGER.info("Union all data and perform cross validation")

    union_data = train_data.append(test_data)

    cross_val(cls_pipeline, union_data, cfg)

    del union_data

    LOGGER.info("Train classifier")

    train_features, train_target = prepare_date(train_data,
                                                cfg.data_config.unique_values_limit,
                                                cfg.data_config.target_variable)

    cls_pipeline.fit(train_features, train_target)

    test_features, test_target = prepare_date(test_data,
                                              cfg.data_config.unique_values_limit,
                                              cfg.data_config.target_variable)

    predicted_proba = cls_pipeline.predict_proba(test_features)[:, 1]

    roc_auc_score = metrics.roc_auc_score(test_target, predicted_proba)

    metric_path = os.path.join(hydra.utils.get_original_cwd(), cfg.output_metric)

    LOGGER.info("ROC AUC score: %f", roc_auc_score)
    LOGGER.info("Save metric to %s", metric_path)

    os.makedirs(os.path.dirname(metric_path), exist_ok=True)

    with open(metric_path, "w", encoding="utf-8") as file:
        metric = {"ROC AUC": roc_auc_score}
        json.dump(metric, file)

    model_path = os.path.join(hydra.utils.get_original_cwd(), cfg.model_path)

    LOGGER.info("Save trained model to %s", model_path)

    dump_pickle(cls_pipeline, model_path)


if __name__ == "__main__":
    train()

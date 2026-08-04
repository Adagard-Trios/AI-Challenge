"""
models/anomaly-detection/src/utils/metrics.py
Clustering and anomaly detection metrics for model evaluation
"""
import numpy as np
from typing import Dict, Any, Optional, List
import logging

logger = logging.getLogger("metrics")

# Scikit-learn metrics
try:
    from sklearn.metrics import (
        silhouette_score,
        calinski_harabasz_score,
        davies_bouldin_score,
        adjusted_rand_score,
        normalized_mutual_info_score
    )
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("scikit-learn not available for metrics")


def calculate_clustering_metrics(
    X: np.ndarray,
    labels: np.ndarray,
    true_labels: Optional[np.ndarray] = None
) -> Dict[str, float]:
    """
    Calculate comprehensive clustering quality metrics.
    
    Args:
        X: Feature matrix (n_samples, n_features)
        labels: Predicted cluster labels
        true_labels: Optional ground truth labels for supervised metrics
        
    Returns:
        Dict of metric_name -> metric_value
    """
    if not SKLEARN_AVAILABLE:
        logger.warning("sklearn not available, returning empty metrics")
        return {}

    metrics = {}

    # Filter out noise points (label=-1) for some metrics
    valid_mask = labels >= 0
    n_clusters = len(set(labels[valid_mask]))

    # Need at least 2 clusters and >1 samples for metrics
    if n_clusters < 2 or np.sum(valid_mask) < 2:
        metrics["n_clusters"] = n_clusters
        metrics["n_noise_points"] = np.sum(labels == -1)
        metrics["error"] = "insufficient_clusters"
        return metrics

    # Internal metrics (don't need ground truth)
    try:
        # Silhouette Score: -1 (bad) to 1 (good)
        # Measures how similar objects are to their own cluster vs other clusters
        metrics["silhouette_score"] = float(silhouette_score(
            X[valid_mask], labels[valid_mask]
        ))
    except Exception as e:
        logger.debug(f"Silhouette score failed: {e}")
        metrics["silhouette_score"] = None

    try:
        # Calinski-Harabasz Index: Higher is better
        # Ratio of between-cluster dispersion to within-cluster dispersion
        metrics["calinski_harabasz_score"] = float(calinski_harabasz_score(
            X[valid_mask], labels[valid_mask]
        ))
    except Exception as e:
        logger.debug(f"Calinski-Harabasz failed: {e}")
        metrics["calinski_harabasz_score"] = None

    try:
        # Davies-Bouldin Index: Lower is better
        # Average similarity between clusters
        metrics["davies_bouldin_score"] = float(davies_bouldin_score(
            X[valid_mask], labels[valid_mask]
        ))
    except Exception as e:
        logger.debug(f"Davies-Bouldin failed: {e}")
        metrics["davies_bouldin_score"] = None

    # Cluster statistics
    metrics["n_clusters"] = n_clusters
    metrics["n_samples"] = len(labels)
    metrics["n_noise_points"] = int(np.sum(labels == -1))
    metrics["noise_ratio"] = float(np.sum(labels == -1) / len(labels))

    # Cluster size statistics
    cluster_sizes = [np.sum(labels == i) for i in range(n_clusters)]
    metrics["min_cluster_size"] = int(min(cluster_sizes)) if cluster_sizes else 0
    metrics["max_cluster_size"] = int(max(cluster_sizes)) if cluster_sizes else 0
    metrics["mean_cluster_size"] = float(np.mean(cluster_sizes)) if cluster_sizes else 0

    # External metrics (if ground truth provided)
    if true_labels is not None:
        try:
            # Adjusted Rand Index: -1 to 1, 1=perfect, 0=random
            metrics["adjusted_rand_score"] = float(adjusted_rand_score(
                true_labels, labels
            ))
        except Exception as e:
            logger.debug(f"ARI failed: {e}")

        try:
            # Normalized Mutual Information: 0 to 1, 1=perfect agreement
            metrics["normalized_mutual_info"] = float(normalized_mutual_info_score(
                true_labels, labels
            ))
        except Exception as e:
            logger.debug(f"NMI failed: {e}")

    return metrics


def calculate_anomaly_metrics(
    labels: np.ndarray,
    predicted_anomalies: np.ndarray,
    true_anomalies: Optional[np.ndarray] = None
) -> Dict[str, float]:
    """
    Calculate anomaly detection metrics.
    
    Args:
        labels: Cluster labels or -1 for anomalies
        predicted_anomalies: Boolean array of predicted anomaly flags
        true_anomalies: Optional ground truth anomaly flags
        
    Returns:
        Dict of metric_name -> metric_value
    """
    metrics = {}

    n_samples = len(labels)
    n_predicted_anomalies = int(np.sum(predicted_anomalies))

    metrics["n_samples"] = n_samples
    metrics["n_predicted_anomalies"] = n_predicted_anomalies
    metrics["anomaly_rate"] = float(n_predicted_anomalies / n_samples) if n_samples > 0 else 0

    # If ground truth available, calculate precision/recall
    if true_anomalies is not None:
        n_true_anomalies = int(np.sum(true_anomalies))

        # True positives: predicted AND actual anomalies
        tp = int(np.sum(predicted_anomalies & true_anomalies))
        # False positives: predicted anomaly but not actual
        fp = int(np.sum(predicted_anomalies & ~true_anomalies))
        # False negatives: not predicted but actual anomaly
        fn = int(np.sum(~predicted_anomalies & true_anomalies))
        # True negatives
        tn = int(np.sum(~predicted_anomalies & ~true_anomalies))

        metrics["true_positives"] = tp
        metrics["false_positives"] = fp
        metrics["false_negatives"] = fn
        metrics["true_negatives"] = tn

        # Precision: TP / (TP + FP)
        metrics["precision"] = float(tp / (tp + fp)) if (tp + fp) > 0 else 0

        # Recall: TP / (TP + FN)
        metrics["recall"] = float(tp / (tp + fn)) if (tp + fn) > 0 else 0

        # F1 Score
        if metrics["precision"] + metrics["recall"] > 0:
            metrics["f1_score"] = float(
                2 * metrics["precision"] * metrics["recall"] /
                (metrics["precision"] + metrics["recall"])
            )
        else:
            metrics["f1_score"] = 0

    return metrics


def calculate_optuna_objective(
    X: np.ndarray,
    labels: np.ndarray,
    objective_type: str = "silhouette"
) -> float:
    """
    Calculate objective value for Optuna optimization.
    
    Args:
        X: Feature matrix
        labels: Predicted labels
        objective_type: 'silhouette', 'calinski', or 'combined'
        
    Returns:
        Objective value (higher is better)
    """
    metrics = calculate_clustering_metrics(X, labels)

    # Check for errors
    if "error" in metrics:
        return -1.0  # Return bad score for failed clustering

    if objective_type == "silhouette":
        score = metrics.get("silhouette_score")
        return score if score is not None else -1.0

    elif objective_type == "calinski":
        score = metrics.get("calinski_harabasz_score")
        # Normalize to 0-1 range (approximate)
        return min(score / 1000, 1.0) if score is not None else -1.0

    elif objective_type == "combined":
        # Weighted combination of metrics
        silhouette = metrics.get("silhouette_score", -1)
        calinski = min(metrics.get("calinski_harabasz_score", 0) / 1000, 1)
        davies = metrics.get("davies_bouldin_score", 10)

        # Davies-Bouldin is lower=better, invert it
        davies_inv = 1 / (1 + davies) if davies is not None else 0

        # Weighted combination
        combined = (0.4 * silhouette + 0.3 * calinski + 0.3 * davies_inv)
        return float(combined)

    return -1.0


def format_metrics_report(metrics: Dict[str, Any]) -> str:
    """
    Format metrics dictionary as a readable report.
    
    Args:
        metrics: Dictionary of metric values
        
    Returns:
        Formatted string report
    """
    lines = ["=" * 50]
    lines.append("CLUSTERING METRICS REPORT")
    lines.append("=" * 50)

    for key, value in metrics.items():
        if value is None:
            value_str = "N/A"
        elif isinstance(value, float):
            value_str = f"{value:.4f}"
        else:
            value_str = str(value)

        lines.append(f"{key:30s}: {value_str}")

    lines.append("=" * 50)
    return "\n".join(lines)

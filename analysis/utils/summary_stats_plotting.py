import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

def compute_feature_rsd(table: pd.DataFrame, qc_sample_cols: list[str]) -> pd.Series:
    qc_values = table[qc_sample_cols]
    means = qc_values.mean(axis=1, skipna=True)
    stds = qc_values.std(axis=1, skipna=True)
    n_valid = qc_values.notna().sum(axis=1)
    return (stds / means * 100).where(n_valid >= 2)

def prepare_pca_matrix(table: pd.DataFrame, sample_cols: list[str], min_presence_frac: float) -> pd.DataFrame:
    intensities = table[sample_cols]
    presence_frac = intensities.notna().sum(axis=1) / len(sample_cols)
    filtered = intensities[presence_frac >= min_presence_frac]
    global_min = filtered.min().min()
    imputed = filtered.fillna(global_min / 2)
    log_transformed = np.log2(imputed + 1)
    return log_transformed.T

def compute_pca_scores(matrix: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    scaled = StandardScaler().fit_transform(matrix)
    pca = PCA(n_components=2)
    scores = pca.fit_transform(scaled)
    scores_df = pd.DataFrame(scores, columns=["PC1", "PC2"], index=matrix.index)
    return scores_df, pca.explained_variance_ratio_

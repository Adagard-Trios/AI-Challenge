"""
models/anomaly-detection/src/components/data_validation.py
Data validation component based on schema.yaml
"""
import os
import yaml
import pandas as pd
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from ..entity import DataValidationConfig, DataValidationArtifact

logger = logging.getLogger("data_validation")


class DataValidation:
    """
    Data validation component that validates feed data against schema.
    Checks column types, required fields, and value constraints.
    """

    def __init__(self, config: Optional[DataValidationConfig] = None):
        """
        Initialize data validation component.
        
        Args:
            config: Optional configuration, uses defaults if None
        """
        self.config = config or DataValidationConfig()

        # Ensure output directory exists
        Path(self.config.output_directory).mkdir(parents=True, exist_ok=True)

        # Load schema
        self.schema = self._load_schema()

        logger.info(f"[DataValidation] Initialized with schema: {self.config.schema_file}")

    def _load_schema(self) -> Dict[str, Any]:
        """Load schema from YAML file"""
        if not os.path.exists(self.config.schema_file):
            logger.warning(f"[DataValidation] Schema file not found: {self.config.schema_file}")
            return {}

        try:
            with open(self.config.schema_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"[DataValidation] Failed to load schema: {e}")
            return {}

    def _validate_required_columns(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Check that all required columns are present.
        
        Returns:
            List of validation errors
        """
        errors = []

        for col in self.config.required_columns:
            if col not in df.columns:
                errors.append({
                    "type": "missing_column",
                    "column": col,
                    "message": f"Required column '{col}' is missing"
                })

        return errors

    def _validate_column_types(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Validate column data types based on schema.
        
        Returns:
            List of validation errors
        """
        errors = []

        if "feed_columns" not in self.schema:
            return errors

        for col_name, col_spec in self.schema["feed_columns"].items():
            if col_name not in df.columns:
                continue

            expected_dtype = col_spec.get("dtype", "str")

            # Check for null values in required columns
            if col_spec.get("required", False):
                null_count = df[col_name].isna().sum()
                if null_count > 0:
                    errors.append({
                        "type": "null_values",
                        "column": col_name,
                        "count": int(null_count),
                        "message": f"Column '{col_name}' has {null_count} null values"
                    })

            # Check min/max length for strings
            if expected_dtype == "str" and col_name in df.columns:
                min_len = col_spec.get("min_length", 0)
                max_len = col_spec.get("max_length", float('inf'))

                if min_len > 0:
                    short_count = (df[col_name].fillna("").str.len() < min_len).sum()
                    if short_count > 0:
                        errors.append({
                            "type": "min_length_violation",
                            "column": col_name,
                            "count": int(short_count),
                            "message": f"Column '{col_name}' has {short_count} values shorter than {min_len}"
                        })

            # Check allowed values
            allowed = col_spec.get("allowed_values")
            if allowed and col_name in df.columns:
                invalid_mask = ~df[col_name].isin(allowed) & df[col_name].notna()
                invalid_count = invalid_mask.sum()
                if invalid_count > 0:
                    errors.append({
                        "type": "invalid_value",
                        "column": col_name,
                        "count": int(invalid_count),
                        "allowed": allowed,
                        "message": f"Column '{col_name}' has {invalid_count} values not in allowed list"
                    })

        return errors

    def _validate_numeric_ranges(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        """
        Validate numeric column ranges.
        
        Returns:
            List of validation errors
        """
        errors = []

        if "feed_columns" not in self.schema:
            return errors

        for col_name, col_spec in self.schema["feed_columns"].items():
            if col_name not in df.columns:
                continue

            expected_dtype = col_spec.get("dtype")

            if expected_dtype in ["int", "float"]:
                min_val = col_spec.get("min_value")
                max_val = col_spec.get("max_value")

                if min_val is not None:
                    try:
                        below_count = (pd.to_numeric(df[col_name], errors='coerce') < min_val).sum()
                        if below_count > 0:
                            errors.append({
                                "type": "below_minimum",
                                "column": col_name,
                                "count": int(below_count),
                                "min_value": min_val,
                                "message": f"Column '{col_name}' has {below_count} values below {min_val}"
                            })
                    except Exception:
                        pass

                if max_val is not None:
                    try:
                        above_count = (pd.to_numeric(df[col_name], errors='coerce') > max_val).sum()
                        if above_count > 0:
                            errors.append({
                                "type": "above_maximum",
                                "column": col_name,
                                "count": int(above_count),
                                "max_value": max_val,
                                "message": f"Column '{col_name}' has {above_count} values above {max_val}"
                            })
                    except Exception:
                        pass

        return errors

    def initiate_data_validation(self, data_path: str) -> DataValidationArtifact:
        """
        Execute data validation pipeline.
        
        Args:
            data_path: Path to input data (parquet or csv)
            
        Returns:
            DataValidationArtifact with validation results
        """
        logger.info(f"[DataValidation] Validating: {data_path}")

        # Load data
        if data_path.endswith(".parquet"):
            df = pd.read_parquet(data_path)
        elif data_path.endswith(".csv"):
            df = pd.read_csv(data_path)
        else:
            raise ValueError(f"Unsupported file format: {data_path}")

        total_records = len(df)
        logger.info(f"[DataValidation] Loaded {total_records} records")

        # Run validations
        all_errors = []
        all_errors.extend(self._validate_required_columns(df))
        all_errors.extend(self._validate_column_types(df))
        all_errors.extend(self._validate_numeric_ranges(df))

        # Calculate valid/invalid records
        invalid_records = 0
        for error in all_errors:
            if "count" in error:
                invalid_records = max(invalid_records, error["count"])

        valid_records = total_records - invalid_records
        validation_status = len(all_errors) == 0

        # Log validation results
        if validation_status:
            logger.info("[DataValidation] ✓ All validations passed")
        else:
            logger.warning(f"[DataValidation] ⚠ Found {len(all_errors)} validation issues")
            for error in all_errors[:5]:  # Log first 5
                logger.warning(f"  - {error['message']}")

        # Save validated data (even with warnings, we continue)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        validated_path = Path(self.config.output_directory) / f"validated_data_{timestamp}.parquet"
        df.to_parquet(validated_path, index=False)

        # Save validation report
        report_path = Path(self.config.output_directory) / f"validation_report_{timestamp}.yaml"
        report = {
            "validation_timestamp": timestamp,
            "input_path": data_path,
            "total_records": total_records,
            "valid_records": valid_records,
            "invalid_records": invalid_records,
            "validation_status": validation_status,
            "errors": all_errors
        }
        with open(report_path, 'w') as f:
            yaml.dump(report, f, default_flow_style=False)

        artifact = DataValidationArtifact(
            validated_data_path=str(validated_path),
            validation_report_path=str(report_path),
            total_records=total_records,
            valid_records=valid_records,
            invalid_records=invalid_records,
            validation_status=validation_status,
            validation_errors=all_errors
        )

        logger.info(f"[DataValidation] ✓ Complete: {valid_records}/{total_records} valid records")
        return artifact

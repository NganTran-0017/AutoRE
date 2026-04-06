"""Alloy Analyzer execution utility."""
import subprocess
import json
from pathlib import Path
from typing import Dict, List, Any, Optional


class AlloyExecutor:
    """Executes Alloy Analyzer and parses results."""

    def __init__(self, alloy_jar_path: str = "tools/alloy.jar"):
        """
        Initialize Alloy executor.

        Args:
            alloy_jar_path: Path to Alloy Analyzer JAR file
        """
        self.alloy_jar_path = Path(alloy_jar_path)
        if not self.alloy_jar_path.exists():
            raise FileNotFoundError(f"Alloy JAR not found at: {self.alloy_jar_path}")

    def execute(
        self,
        model_path: Path,
        output_dir: Path,
        timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Execute Alloy Analyzer on a model.

        Args:
            model_path: Path to Alloy model file (.als)
            output_dir: Directory to save output JSON files
            timeout: Execution timeout in seconds

        Returns:
            Dictionary with execution results and metadata
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Build command
        cmd = [
            "java",
            "-jar",
            str(self.alloy_jar_path),
            "-t", "json",
            "-o", str(output_dir) + "/",
            str(model_path)
        ]

        try:
            # Execute Alloy Analyzer
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            # Parse results
            output_files = list(output_dir.glob("*.json"))

            execution_result = {
                "success": result.returncode == 0,
                "return_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "output_files": [str(f) for f in output_files],
                "analysis": self._analyze_results(output_files)
            }

            return execution_result

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Execution timeout",
                "timeout": timeout
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def _analyze_results(self, output_files: List[Path]) -> Dict[str, Any]:
        """
        Analyze Alloy Analyzer output files.

        Args:
            output_files: List of output JSON files

        Returns:
            Analysis summary
        """
        if not output_files:
            return {
                "has_results": False,
                "message": "No output files generated"
            }

        analysis = {
            "has_results": True,
            "num_files": len(output_files),
            "files": [],
            "has_syntax_errors": False,
            "has_counterexamples": False,
            "has_satisfying_instances": False,
            "syntax_errors": [],
            "counterexamples": [],
            "instances": []
        }

        for file_path in output_files:
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)

                file_analysis = {
                    "filename": file_path.name,
                    "path": str(file_path),
                    "type": self._determine_result_type(data)
                }

                # Categorize the result
                if file_analysis["type"] == "syntax_error":
                    analysis["has_syntax_errors"] = True
                    analysis["syntax_errors"].append({
                        "file": file_path.name,
                        "data": data
                    })
                elif file_analysis["type"] == "counterexample":
                    analysis["has_counterexamples"] = True
                    analysis["counterexamples"].append({
                        "file": file_path.name,
                        "data": data
                    })
                elif file_analysis["type"] == "instance":
                    analysis["has_satisfying_instances"] = True
                    analysis["instances"].append({
                        "file": file_path.name,
                        "data": data
                    })

                analysis["files"].append(file_analysis)

            except json.JSONDecodeError:
                analysis["files"].append({
                    "filename": file_path.name,
                    "path": str(file_path),
                    "type": "parse_error",
                    "error": "Failed to parse JSON"
                })
            except Exception as e:
                analysis["files"].append({
                    "filename": file_path.name,
                    "path": str(file_path),
                    "type": "error",
                    "error": str(e)
                })

        return analysis

    def _determine_result_type(self, data: Dict[str, Any]) -> str:
        """
        Determine the type of Alloy result.

        Args:
            data: Parsed JSON data

        Returns:
            Result type string
        """
        # Check for syntax or compilation errors
        if "error" in data or "errors" in data:
            return "syntax_error"

        # Check for counterexamples (violations)
        if "counterexample" in data or "is_counterexample" in data:
            if data.get("counterexample", False) or data.get("is_counterexample", False):
                return "counterexample"

        # Check for satisfying instances
        if "instance" in data or "satisfiable" in data:
            if data.get("satisfiable", True):
                return "instance"

        # Default to instance type
        return "instance"

    def get_summary(self, analysis: Dict[str, Any]) -> str:
        """
        Get human-readable summary of analysis.

        Args:
            analysis: Analysis dictionary

        Returns:
            Summary string
        """
        if not analysis.get("has_results", False):
            return "No analysis results available."

        summary_parts = [
            f"Analysis Results ({analysis['num_files']} file(s)):",
            ""
        ]

        if analysis["has_syntax_errors"]:
            summary_parts.append(f"❌ Syntax Errors Found: {len(analysis['syntax_errors'])}")
        else:
            summary_parts.append("✓ No syntax errors")

        if analysis["has_counterexamples"]:
            summary_parts.append(f"⚠ Counterexamples Found: {len(analysis['counterexamples'])}")
        else:
            summary_parts.append("✓ No counterexamples")

        if analysis["has_satisfying_instances"]:
            summary_parts.append(f"✓ Satisfying Instances: {len(analysis['instances'])}")
        else:
            summary_parts.append("⚠ No satisfying instances")

        return "\n".join(summary_parts)
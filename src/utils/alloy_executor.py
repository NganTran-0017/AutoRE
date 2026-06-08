"""Alloy Analyzer execution utility."""
import subprocess
import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple


class AlloyExecutor:
    """Executes Alloy Analyzer and parses results."""

    def __init__(self, alloy_jar_path: str = "tools/alloy-6.2.0.jar"):
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
            Dictionary with execution results and metadata.
            'success' indicates whether the TOOL executed successfully,
            NOT whether the model is valid. Check analysis['has_syntax_errors']
            for model validity.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        # Build command
        cmd = [
            "java",
            "-jar",
            str(self.alloy_jar_path),
            "exec",  # Execute command
            "-t", "json",
            "-f",  # Force overwrite existing files
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
            
            # Analyze the results (pass model_path for code snippet extraction)
            analysis = self._analyze_results(output_files, result.stdout, result.stderr, model_path)

            # Check if this was a tool execution failure vs model syntax errors
            # Tool executed successfully if:
            # 1. We got output/analysis, OR
            # 2. We have syntax errors (means Alloy parsed the model and found issues)
            tool_executed = (
                analysis.get("has_results", False) or 
                analysis.get("has_syntax_errors", False) or
                result.returncode == 0
            )

            # If tool didn't execute and we have stderr that looks like a system error
            if not tool_executed and result.stderr:
                stderr_lower = result.stderr.lower()
                # Check for actual execution failures
                if any(err in stderr_lower for err in [
                    "error: could not find or load main class",
                    "java.lang.classnotfoundexception",
                    "no such file or directory",
                    "command not found",
                    "permission denied"
                ]):
                    return {
                        "success": False,
                        "error": "Alloy Analyzer tool execution failed",
                        "return_code": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr
                    }

            execution_result = {
                "success": True,  # Tool executed (even if model has syntax errors)
                "return_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "output_files": [str(f) for f in output_files],
                "analysis": analysis
            }

            return execution_result

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Execution timeout",
                "timeout": timeout
            }
        except FileNotFoundError as e:
            return {
                "success": False,
                "error": f"Alloy JAR or Java not found: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Alloy execution failed: {str(e)}"
            }

    def _parse_cli_output(self, stdout: str, stderr: str, model_path: Optional[Path] = None) -> Tuple[Dict[str, Dict], List[Dict[str, Any]]]:
        """
        Parse Alloy Analyzer CLI output to extract command information and syntax errors.

        Args:
            stdout: Standard output from Alloy execution
            stderr: Standard error from Alloy execution
            model_path: Optional path to the Alloy model file for code snippet extraction

        Returns:
            Tuple of (command_map, syntax_errors)
            - command_map: Dict mapping command_name to {type, result, number}
            - syntax_errors: List of structured error dictionaries
        """
        command_map = {}
        syntax_errors = []

        # Combine stdout and stderr for error detection
        combined_output = stdout + "\n" + stderr
        
        # Check for syntax errors
        if "[main] ERROR alloy" in combined_output or "Syntax error" in combined_output or "Type error" in combined_output:
            syntax_errors = self._extract_syntax_errors(combined_output, model_path)

        # Parse command output lines
        # Format: <number>. <type> <name> <spaces> [instances] <result>
        # Examples:
        #   "00. run   R1                       1/1     SAT"
        #   "08. check assertR4_1               0       UNSAT"
        # Note: UNSAT has "0" instead of "N/N" for instances
        # NOTE: Alloy 6 outputs command results to STDERR, not STDOUT
        # Use flexible pattern to handle variable whitespace
        pattern = r'^\s*(\d+)\.\s+(run|check)\s+(\S+)\s+.*?(?:(\d+/\d+)\s+)?(SAT|UNSAT)\s*$'

        # Check both stdout and stderr (Alloy 6 uses stderr for command results)
        for line in (stdout + '\n' + stderr).split('\n'):
            match = re.match(pattern, line.strip())
            if match:
                number, cmd_type, cmd_name, instances_str, result = match.groups()
                command_map[cmd_name] = {
                    "number": int(number),
                    "type": cmd_type,  # "run" or "check"
                    "result": result,  # "SAT" or "UNSAT"
                    "name": cmd_name,
                    "instances": instances_str  # e.g., "1/1", "0"
                }

        return command_map, syntax_errors

    def _find_containing_block(
        self, 
        file_path: str, 
        line_num: int
    ) -> Optional[Tuple[int, int, str]]:
        """
        Find the complete syntactic block containing the error using keyword-to-keyword boundaries.
        
        Args:
            file_path: Path to the .als file
            line_num: Error line number (1-indexed as reported by Alloy)
        
        Returns:
            (start_line, end_line, block_type) or None if not found
            - start_line: 1-indexed line where block starts
            - end_line: 1-indexed line where block ends
            - block_type: keyword name with block name (e.g., "pred EmergencyCoverage_Positive")
        """
        import re
        
        BLOCK_KEYWORDS = ['pred', 'fact', 'fun', 'sig', 'assert', 'enum']
        BOUNDARY_KEYWORDS = ['pred', 'fact', 'fun', 'sig', 'assert', 'enum', 'run', 'check']
        MAX_BLOCK_SIZE = 100
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Error on first line - no backward search possible
            if line_num <= 1:
                return None
            
            # Convert to 0-indexed
            error_idx = line_num - 1
            
            # Step 1: Search BACKWARD from error line to find closest block keyword
            keyword_pattern = re.compile(r'^\s*(' + '|'.join(BLOCK_KEYWORDS) + r')\b')
            block_start_idx = None
            block_keyword = None
            block_name = None
            
            for i in range(error_idx, -1, -1):
                match = keyword_pattern.match(lines[i])
                if match:
                    block_start_idx = i
                    block_keyword = match.group(1)
                    # Extract block name if present (e.g., "pred MyPredicate" -> "MyPredicate")
                    name_match = re.match(r'^\s*\w+\s+(\w+)', lines[i])
                    if name_match:
                        block_name = name_match.group(1)
                    break
            
            if block_start_idx is None:
                return None  # No block keyword found
            
            # Step 2: Search FORWARD from block start to find next boundary keyword
            # Use BOUNDARY_KEYWORDS (includes run/check) to find where the block ends
            boundary_pattern = re.compile(r'^\s*(' + '|'.join(BOUNDARY_KEYWORDS) + r')\b')
            block_end_idx = None
            
            for i in range(block_start_idx + 1, len(lines)):
                if boundary_pattern.match(lines[i]):
                    block_end_idx = i - 1  # End just before next keyword
                    break
            
            if block_end_idx is None:
                # No next keyword found - use end of file
                block_end_idx = len(lines) - 1
            
            # Step 3: Trim trailing blank lines and comments
            # Comments between blocks should not be included in either block
            while block_end_idx > block_start_idx:
                line = lines[block_end_idx].strip()
                # Stop trimming if we hit a non-blank, non-comment line
                if line != '' and not line.startswith('//'):
                    break
                block_end_idx -= 1
            
            # Check block size
            block_size = block_end_idx - block_start_idx + 1
            if block_size > MAX_BLOCK_SIZE:
                return None  # Block too large, fallback to context lines
            
            # Create block type description
            if block_name:
                block_type = f"{block_keyword} {block_name}"
            else:
                block_type = block_keyword
            
            # Return 1-indexed line numbers
            return (block_start_idx + 1, block_end_idx + 1, block_type)
            
        except Exception as e:
            # If anything fails, return None to fallback to context lines
            return None

    def _extract_code_snippet(
        self, 
        file_path: str, 
        line_num: int, 
        col_num: int, 
        context_lines: int = 2
    ) -> str:
        """
        Extract code snippet from file with error marker.
        First attempts to extract the complete syntactic block (pred, fact, fun, sig, assert, enum).
        Falls back to ±context_lines if block extraction fails or block is too large.
        
        Args:
            file_path: Path to the .als file
            line_num: Line number (1-indexed as reported by Alloy)
            col_num: Column number (1-indexed as reported by Alloy)
            context_lines: Number of lines before/after to include (fallback only)
        
        Returns:
            Formatted code snippet with error marker
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Convert to 0-indexed
            line_idx = line_num - 1
            
            # Validate line number
            if line_idx < 0 or line_idx >= len(lines):
                return f"(Line {line_num} is out of range in file)"
            
            # Try to find complete block first
            block_info = self._find_containing_block(file_path, line_num)
            
            if block_info:
                # Extract complete block
                start_line, end_line, block_type = block_info
                start_idx = start_line - 1
                end_idx = end_line
                
                snippet_lines = []
                snippet_lines.append(f"CODE CONTEXT - COMPLETE BLOCK: {block_type} (lines {start_line}-{end_line}):")

                for i in range(start_idx, end_idx):
                    line_content = lines[i].rstrip('\n')

                    # Skip comment lines (but keep line numbers intact)
                    if not line_content.lstrip().startswith('//'):
                        snippet_lines.append(f"{i + 1:3d}: {line_content}")

                        # Add error marker right after the error line
                        if i == line_idx:
                            prefix_len = len(f"{i + 1:3d}: ")
                            marker_pos = prefix_len + col_num - 1
                            marker = ' ' * marker_pos + '^^ ERROR at column ' + str(col_num)
                            snippet_lines.append(marker)

                return '\n'.join(snippet_lines)
            
            else:
                # Fallback to context lines approach
                start_idx = max(0, line_idx - context_lines)
                end_idx = min(len(lines), line_idx + context_lines + 1)

                snippet_lines = []
                snippet_lines.append(f"CODE CONTEXT (lines {start_idx + 1}-{end_idx}):")

                for i in range(start_idx, end_idx):
                    line_content = lines[i].rstrip('\n')

                    # Skip comment lines (but keep line numbers intact)
                    if not line_content.lstrip().startswith('//'):
                        snippet_lines.append(f"{i + 1:3d}: {line_content}")

                        # Add error marker right after the error line
                        if i == line_idx:
                            prefix_len = len(f"{i + 1:3d}: ")
                            marker_pos = prefix_len + col_num - 1
                            marker = ' ' * marker_pos + '^^ ERROR at column ' + str(col_num)
                            snippet_lines.append(marker)

                return '\n'.join(snippet_lines)
            
        except FileNotFoundError:
            return f"(Could not read file: {file_path})"
        except Exception as e:
            return f"(Error extracting snippet: {str(e)})"

    def _extract_syntax_errors(self, output: str, model_path: Optional[Path] = None) -> List[Dict[str, Any]]:
        """
        Extract structured syntax error information from Alloy CLI output.

        Args:
            output: Combined stdout and stderr from Alloy execution
            model_path: Optional path to the Alloy model file for code snippet extraction

        Returns:
            List of structured error dictionaries with file, line, column, message, etc.
        """
        errors = []
        lines = output.split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Look for syntax error lines
            # Pattern 1: "[main] ERROR alloy - ... Syntax error in <file> at line <N> column <M>:"
            # Pattern 2: "Syntax error in <file> at line <N> column <M>:"
            if "Syntax error in" in line or ("[main] ERROR alloy" in line and "Syntax error" in line):
                # Extract file path, line number, and column number
                # Pattern: "Syntax error in /path/to/file.als at line 59 column 19:"
                import re
                match = re.search(r'Syntax error in (.+?\.als) at line (\d+) column (\d+)', line)
                
                if match:
                    file_path = match.group(1)
                    line_num = int(match.group(2))
                    col_num = int(match.group(3))
                    
                    # Extract the main error message (everything before "Syntax error")
                    error_intro = line.split("Syntax error")[0].strip()
                    if error_intro and error_intro != "[main] ERROR alloy -":
                        error_intro = error_intro.replace("[main] ERROR alloy -", "").strip()
                    
                    # Look ahead for context (next 1-3 lines usually contain helpful info)
                    context_lines = []
                    j = i + 1
                    # Capture next lines until we hit a stack trace or empty line
                    while j < len(lines) and j < i + 4:
                        next_line = lines[j].strip()
                        # Stop at stack traces or error summary
                        if next_line.startswith("at ") or next_line == "Error" or not next_line:
                            break
                        # Include helpful context like "There are X possible tokens..."
                        if next_line:
                            context_lines.append(next_line)
                        j += 1
                    
                    # Build user-friendly error message
                    error_message = f"Syntax error at line {line_num}, column {col_num}"
                    
                    # Add context if available
                    context = "\n".join(context_lines) if context_lines else ""
                    
                    # Extract code snippet if model_path is available
                    code_snippet = ""
                    if model_path and model_path.exists():
                        code_snippet = self._extract_code_snippet(
                            str(model_path), 
                            line_num, 
                            col_num
                        )
                    
                    # Create structured error
                    error_obj = {
                        "type": "syntax_error",
                        "file": file_path,
                        "line": line_num,
                        "column": col_num,
                        "message": error_message,
                        "context": context,
                        "code_snippet": code_snippet,  # NEW field
                        "full_text": line + ("\n" + "\n".join(context_lines) if context_lines else "")
                    }
                    
                    errors.append(error_obj)
                    i = j  # Skip past the lines we've already processed
                    continue
            
            # Also look for Type errors (similar format to Syntax errors)
            elif "Type error in" in line or ("[main] ERROR alloy" in line and "Type error" in line):
                # Extract file path, line number, and column number
                # Pattern: "Type error in /path/to/file.als at line 131 column 54:"
                import re
                match = re.search(r'Type error in (.+?\.als) at line (\d+) column (\d+)', line)
                
                if match:
                    file_path = match.group(1)
                    line_num = int(match.group(2))
                    col_num = int(match.group(3))
                    
                    # Look ahead for context (next lines contain type mismatch details)
                    context_lines = []
                    j = i + 1
                    # Capture next lines until we hit a stack trace or "Type error" repetition
                    while j < len(lines) and j < i + 6:
                        next_line = lines[j].strip()
                        # Stop at stack traces or another error
                        if next_line.startswith("at ") or next_line == "Error":
                            break
                        # Stop at duplicate "Type error" line (Alloy reports twice)
                        if "Type error in" in next_line and j > i + 1:
                            break
                        # Include helpful context like "This must be...", "Instead, it has..."
                        if next_line:
                            context_lines.append(next_line)
                        # Stop after we get both "This must be" and "Instead, it has"
                        if len(context_lines) >= 3 and any("Instead" in line for line in context_lines):
                            break
                        j += 1
                    
                    # Build user-friendly error message
                    error_message = f"Type error at line {line_num}, column {col_num}"
                    
                    # Add context if available
                    context = "\n".join(context_lines) if context_lines else ""
                    
                    # Extract code snippet if model_path is available
                    code_snippet = ""
                    if model_path and model_path.exists():
                        code_snippet = self._extract_code_snippet(
                            str(model_path), 
                            line_num, 
                            col_num
                        )
                    
                    # Create structured error
                    error_obj = {
                        "type": "syntax_error",  # Keep as syntax_error for consistency
                        "file": file_path,
                        "line": line_num,
                        "column": col_num,
                        "message": error_message,
                        "context": context,
                        "code_snippet": code_snippet,
                        "full_text": line + ("\n" + "\n".join(context_lines) if context_lines else "")
                    }
                    
                    errors.append(error_obj)
                    i = j  # Skip past the lines we've already processed
                    continue
            
            i += 1
        
        # If we found structured errors, deduplicate and return them
        if errors:
            # Deduplicate errors by (file, line, column)
            # Alloy Analyzer reports each error twice, we only want the first occurrence
            seen_locations = set()
            deduplicated_errors = []
            
            for error in errors:
                # Create location key from file, line, column
                location_key = (
                    error.get('file'),
                    error.get('line'),
                    error.get('column')
                )
                
                if location_key not in seen_locations:
                    seen_locations.add(location_key)
                    deduplicated_errors.append(error)
            
            return deduplicated_errors
        
        # Fallback: if we detected errors but couldn't parse them, capture raw output
        if "error" in output.lower() and not errors:
            # Find the first occurrence of error and capture surrounding context
            lines = output.split('\n')
            error_context = []
            for i, line in enumerate(lines):
                if "error" in line.lower():
                    # Capture this line and next 2-3 lines
                    error_context.append(line.strip())
                    for j in range(1, min(4, len(lines) - i)):
                        if lines[i + j].strip():
                            error_context.append(lines[i + j].strip())
                    break
            
            if error_context:
                return [{
                    "type": "unknown_error",
                    "message": error_context[0] if error_context else "Unknown error",
                    "full_text": "\n".join(error_context)
                }]
        
        return errors

    def _analyze_results(self, output_files: List[Path], stdout: str, stderr: str, model_path: Optional[Path] = None) -> Dict[str, Any]:
        """
        Analyze Alloy Analyzer output files using CLI output for categorization.

        Args:
            output_files: List of output JSON files
            stdout: Standard output from Alloy execution
            stderr: Standard error from Alloy execution
            model_path: Optional path to the Alloy model file for code snippet extraction

        Returns:
            Analysis summary
        """
        # Parse CLI output to get command information
        command_map, syntax_errors = self._parse_cli_output(stdout, stderr, model_path)

        analysis = {
            "has_results": bool(output_files) or bool(command_map),
            "num_files": len(output_files),
            "files": [],
            "has_syntax_errors": bool(syntax_errors),
            "has_counterexamples": False,
            "has_satisfying_instances": False,
            "syntax_errors": syntax_errors,
            "counterexamples": [],
            "instances": [],
            "unsat_run_commands": [],      # run UNSAT = overconstraint (BAD)
            "unsat_check_commands": [],    # check UNSAT = assertion holds (GOOD)
            "total_run_commands": 0,       # Total run commands
            "total_check_commands": 0,     # Total check commands
            "positive_run_commands": 0,    # Positive run commands (excluding "negative" test cases)
            "satisfied_positive_runs": 0,  # Positive runs with SAT result
            "comprehensive_instance": None,# Most comprehensive instance (All_Requirements or last)
            "sample_instances": []         # Up to 3 instances for Evaluator review
        }

        # Count total commands and categorize UNSAT by type
        for cmd_name, cmd_info in command_map.items():
            cmd_type = cmd_info["type"]

            # Count totals
            if cmd_type == "run":
                analysis["total_run_commands"] += 1

                # Track positive run commands (exclude "negative" test cases)
                is_negative = "negative" in cmd_name.lower()
                if not is_negative:
                    analysis["positive_run_commands"] += 1
                    if cmd_info["result"] == "SAT":
                        analysis["satisfied_positive_runs"] += 1
            elif cmd_type == "check":
                analysis["total_check_commands"] += 1

            # Categorize UNSAT commands
            if cmd_info["result"] == "UNSAT":
                unsat_entry = {
                    "number": cmd_info["number"],
                    "name": cmd_name,
                    "type": cmd_type
                }

                if cmd_type == "run":
                    # run UNSAT = overconstraint (BAD)
                    analysis["unsat_run_commands"].append(unsat_entry)
                elif cmd_type == "check":
                    # check UNSAT = assertion holds (GOOD)
                    analysis["unsat_check_commands"].append(unsat_entry)

        # Process output files
        for file_path in output_files:
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)

                # Extract command name from filename
                # Handle formats like "All_Requirements-solution-0.json" -> "All_Requirements"
                # or "ChainedEmergencyScenario.json" -> "ChainedEmergencyScenario"
                filename_stem = file_path.stem  # Gets filename without extension
                
                # Strip "-solution-N" suffix if present
                if '-solution-' in filename_stem:
                    cmd_name = filename_stem.rsplit('-solution-', 1)[0]
                else:
                    cmd_name = filename_stem

                # Determine type based on CLI output
                if cmd_name in command_map:
                    cmd_info = command_map[cmd_name]
                    if cmd_info["type"] == "run" and cmd_info["result"] == "SAT":
                        result_type = "satisfying_instance"
                    elif cmd_info["type"] == "check" and cmd_info["result"] == "SAT":
                        result_type = "counterexample"
                    else:
                        # Shouldn't happen (UNSAT doesn't create files)
                        result_type = "unknown"
                else:
                    # Fallback if command not found in CLI output
                    result_type = "unknown"

                file_analysis = {
                    "filename": file_path.name,
                    "path": str(file_path),
                    "type": result_type,
                    "command_info": command_map.get(cmd_name, {})
                }

                # Categorize the result
                if result_type == "counterexample":
                    analysis["has_counterexamples"] = True
                    analysis["counterexamples"].append({
                        "file": file_path.name,
                        "command_name": cmd_name,
                        "data": data
                    })
                elif result_type == "satisfying_instance":
                    analysis["has_satisfying_instances"] = True
                    analysis["instances"].append({
                        "file": file_path.name,
                        "command_name": cmd_name,
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

        # Identify comprehensive instance using priority logic
        # Priority: 1. All_Requirements, 2. Longest R-chain, 3. baseline, 4. last
        instances = analysis["instances"]

        if instances:
            # Priority 1: Look for "All_Requirements"
            for inst in instances:
                if inst["command_name"] == "All_Requirements":
                    analysis["comprehensive_instance"] = inst
                    break

            # Priority 2: Find longest R-chain (R1R2R3 > R1R2 > R1)
            if not analysis["comprehensive_instance"]:
                r_chain_instances = []
                for inst in instances:
                    cmd_name = inst["command_name"]
                    # Count consecutive R digits (R1, R1R2, R1R2R3, etc.)
                    if cmd_name.startswith('R') and any(c.isdigit() for c in cmd_name):
                        # Count how many R-number pairs
                        r_count = cmd_name.count('R')
                        r_chain_instances.append((r_count, inst))

                if r_chain_instances:
                    # Sort by R-count descending, return highest
                    r_chain_instances.sort(key=lambda x: x[0], reverse=True)
                    analysis["comprehensive_instance"] = r_chain_instances[0][1]

            # Priority 3: Look for "baseline"
            if not analysis["comprehensive_instance"]:
                for inst in instances:
                    if inst["command_name"] == "baseline":
                        analysis["comprehensive_instance"] = inst
                        break

            # Priority 4: Use last instance as fallback
            if not analysis["comprehensive_instance"]:
                analysis["comprehensive_instance"] = instances[-1]

        # Select up to 3 sample instances for Evaluator review
        # Prioritize: comprehensive + up to 2 others
        sample_set = []
        if analysis["comprehensive_instance"]:
            sample_set.append(analysis["comprehensive_instance"])

        for inst in analysis["instances"]:
            if inst != analysis["comprehensive_instance"] and len(sample_set) < 3:
                sample_set.append(inst)

        analysis["sample_instances"] = sample_set

        return analysis

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
            for ce in analysis["counterexamples"]:
                summary_parts.append(f"  - {ce['command_name']}")
        else:
            summary_parts.append("✓ No counterexamples")

        if analysis["has_satisfying_instances"]:
            summary_parts.append(f"✓ Satisfying Instances: {len(analysis['instances'])}")
            for inst in analysis["instances"]:
                summary_parts.append(f"  - {inst['command_name']}")
        else:
            summary_parts.append("⚠ No satisfying instances")

        if analysis.get("unsat_commands"):
            summary_parts.append(f"\nℹ UNSAT Commands (no instances found): {len(analysis['unsat_commands'])}")
            for unsat in analysis["unsat_commands"]:
                summary_parts.append(f"  - {unsat['type']} {unsat['name']}")

        return "\n".join(summary_parts)
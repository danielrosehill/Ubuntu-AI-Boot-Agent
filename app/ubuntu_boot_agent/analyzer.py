"""Log analysis module using OpenRouter/Claude API."""

import os
import json
import httpx
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def get_config_dir() -> Path:
    """Get the XDG config directory for the application."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
    config_dir = Path(xdg_config) / "ubuntu-boot-agent"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_api_key() -> str:
    """Get API key from config file or environment."""
    # First check config file
    config_file = get_config_dir() / "config.json"
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text())
            if api_key := config.get("openrouter_api_key"):
                return api_key
        except (json.JSONDecodeError, IOError):
            pass

    # Fall back to environment
    return os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENROUTER_API") or ""


def save_api_key(api_key: str) -> None:
    """Save API key to config file."""
    config_file = get_config_dir() / "config.json"

    # Load existing config or create new
    config = {}
    if config_file.exists():
        try:
            config = json.loads(config_file.read_text())
        except (json.JSONDecodeError, IOError):
            pass

    config["openrouter_api_key"] = api_key
    config_file.write_text(json.dumps(config, indent=2))


# For backward compatibility
OPENROUTER_API_KEY = get_api_key()
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are a Linux system administrator expert analyzing boot logs from an Ubuntu system.

Your task is to identify ONLY significant issues that require user attention. Be conservative - don't flag:
- Normal informational messages
- Warnings that are expected/benign
- Hardware detection messages that completed successfully
- Services that started correctly

DO flag:
- Failed services or units
- Hardware errors or failures
- Security-related warnings
- Disk/filesystem errors
- Network configuration failures
- GPU/driver issues that prevent functionality
- Memory or resource exhaustion warnings

For each genuine issue found, provide:
1. A clear, concise problem description
2. The severity level:
   - "urgent": Critical failures requiring immediate attention (failed essential services, security breaches, data loss risk)
   - "moderate": Issues that should be addressed soon (degraded functionality, warnings that may escalate)
   - "mild": Minor issues that can be addressed when convenient (cosmetic errors, non-essential service issues)
3. A specific remediation command or steps
4. The exact log lines that indicate this issue

Respond in JSON format:
{
    "issues": [
        {
            "severity": "urgent|moderate|mild",
            "problem": "Brief description of the issue",
            "details": "Explanation of why this is an issue and its impact",
            "log_snippet": "The exact log lines (1-5 lines) that indicate this issue",
            "remediation": "Specific command or steps to fix",
            "safe_to_auto_run": true/false
        }
    ],
    "summary": "One sentence overall assessment"
}

If no significant issues are found, return:
{
    "issues": [],
    "summary": "No significant issues detected in boot logs."
}
"""


def analyze_logs(log_content: str, failed_services: str = "") -> dict:
    """
    Analyze boot logs using Claude via OpenRouter.

    Args:
        log_content: The boot log text to analyze.
        failed_services: Output from systemctl --failed.

    Returns:
        Dictionary with issues and summary.
    """
    api_key = get_api_key()
    if not api_key:
        return {
            "issues": [{
                "severity": "critical",
                "problem": "OpenRouter API key not configured",
                "details": "No API key found in settings or environment",
                "remediation": "Click Settings in the toolbar to configure your OpenRouter API key",
                "safe_to_auto_run": False
            }],
            "summary": "Configuration error - API key missing"
        }

    # Prepare the log content for analysis
    user_content = f"""Analyze these Ubuntu boot logs and identify any significant issues:

## Boot Logs (journalctl)
```
{log_content[-50000:]}  # Limit to last 50k chars
```

## Failed Services (systemctl --failed)
```
{failed_services}
```

Remember: Only flag genuine issues that need attention. Be conservative.
"""

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/danielrosehill/Ubuntu-AI-Boot-Agent",
                    "X-Title": "Ubuntu Boot Monitoring Agent"
                },
                json={
                    "model": "anthropic/claude-sonnet-4",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_content}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 4096
                }
            )

            response.raise_for_status()
            result = response.json()

            # Extract the content from Claude's response
            content = result["choices"][0]["message"]["content"]

            # Parse JSON from response
            # Handle potential markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            return json.loads(content.strip())

    except httpx.HTTPStatusError as e:
        return {
            "issues": [{
                "severity": "warning",
                "problem": f"API request failed: {e.response.status_code}",
                "details": str(e),
                "remediation": "Check API key and network connection",
                "safe_to_auto_run": False
            }],
            "summary": f"API error: {e.response.status_code}"
        }
    except json.JSONDecodeError as e:
        return {
            "issues": [{
                "severity": "warning",
                "problem": "Failed to parse AI response",
                "details": str(e),
                "remediation": "Check logs manually",
                "safe_to_auto_run": False
            }],
            "summary": "Parse error in AI response"
        }
    except Exception as e:
        return {
            "issues": [{
                "severity": "warning",
                "problem": f"Analysis failed: {type(e).__name__}",
                "details": str(e),
                "remediation": "Check logs manually",
                "safe_to_auto_run": False
            }],
            "summary": f"Error: {str(e)}"
        }


def chat_with_context(
    message: str,
    log_content: str,
    issue: dict = None,
    conversation_history: list = None
) -> str:
    """
    Send a chat message with boot log context.

    Args:
        message: The user's message.
        log_content: The boot log text for context.
        issue: Optional specific issue being discussed.
        conversation_history: List of previous messages [{"role": "user/assistant", "content": "..."}]

    Returns:
        The assistant's response text.
    """
    api_key = get_api_key()
    if not api_key:
        return "Error: OpenRouter API key not configured. Please configure it in Settings."

    chat_system = """You are a helpful Linux system administrator assistant. You have access to the user's boot logs and are helping them diagnose and fix issues.

When suggesting commands:
- Provide clear, step-by-step instructions
- Explain what each command does
- Warn about any risks or side effects
- Prefer safe, reversible actions

Be concise but thorough. Focus on practical solutions."""

    # Build context
    context_parts = [f"## Boot Logs (last 30KB)\n```\n{log_content[-30000:]}\n```"]

    if issue:
        context_parts.append(f"""
## Current Issue Being Discussed
- **Problem**: {issue.get('problem', 'Unknown')}
- **Severity**: {issue.get('severity', 'unknown')}
- **Details**: {issue.get('details', 'N/A')}
- **Log Snippet**: {issue.get('log_snippet', 'N/A')}
- **Suggested Remediation**: {issue.get('remediation', 'N/A')}
""")

    context = "\n".join(context_parts)

    # Build messages
    messages = [
        {"role": "system", "content": chat_system},
        {"role": "user", "content": f"Here is the context for our conversation:\n\n{context}\n\nPlease acknowledge you have this context."},
        {"role": "assistant", "content": "I have the boot logs and issue context. I'm ready to help you diagnose and fix any problems. What would you like to know?"}
    ]

    # Add conversation history
    if conversation_history:
        messages.extend(conversation_history)

    # Add current message
    messages.append({"role": "user", "content": message})

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/danielrosehill/Ubuntu-AI-Boot-Agent",
                    "X-Title": "Ubuntu Boot Monitoring Agent"
                },
                json={
                    "model": "anthropic/claude-sonnet-4",
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 2048
                }
            )

            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"]

    except Exception as e:
        return f"Error: {str(e)}"


if __name__ == "__main__":
    # Test with sample logs
    sample_logs = """
Nov 19 10:00:01 desktop systemd[1]: Started Daily apt download activities.
Nov 19 10:00:02 desktop kernel: [drm:amdgpu_job_timedout [amdgpu]] *ERROR* ring gfx_0.0.0 timeout
Nov 19 10:00:03 desktop systemd[1]: Failed to start Network Manager.
    """

    result = analyze_logs(sample_logs, "● NetworkManager.service loaded failed failed Network Manager")
    print(json.dumps(result, indent=2))

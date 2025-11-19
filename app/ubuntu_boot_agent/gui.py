"""PyQt6 GUI for Ubuntu Boot Monitoring Agent."""

import re
import subprocess
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QScrollArea,
    QFrame,
    QMessageBox,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QSplitter,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor

from .log_capture import capture_boot_logs, capture_priority_logs, get_failed_services
from .analyzer import analyze_logs, chat_with_context, get_api_key, save_api_key


class AnalysisWorker(QThread):
    """Background worker for log analysis."""

    finished = pyqtSignal(dict, str, str)  # results, log_path, log_content
    error = pyqtSignal(str)

    def run(self):
        try:
            # Capture logs
            log_path = capture_priority_logs()
            full_log_path = capture_boot_logs()
            failed_services = get_failed_services()

            # Read log content
            log_content = log_path.read_text()
            full_log_content = full_log_path.read_text()

            # Analyze
            results = analyze_logs(log_content, failed_services)

            self.finished.emit(results, str(full_log_path), full_log_content)
        except Exception as e:
            self.error.emit(str(e))


class ChatWorker(QThread):
    """Background worker for chat responses."""

    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, message: str, log_content: str, issue: dict = None, history: list = None):
        super().__init__()
        self.message = message
        self.log_content = log_content
        self.issue = issue
        self.history = history or []

    def run(self):
        try:
            response = chat_with_context(
                self.message,
                self.log_content,
                self.issue,
                self.history
            )
            self.finished.emit(response)
        except Exception as e:
            self.error.emit(str(e))


class LogSnippetDialog(QDialog):
    """Dialog for viewing log snippet for an issue."""

    def __init__(self, issue: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Log Snippet")
        self.resize(700, 300)

        layout = QVBoxLayout(self)

        # Issue info
        problem_label = QLabel(f"<b>{issue.get('problem', 'Unknown issue')}</b>")
        problem_label.setWordWrap(True)
        layout.addWidget(problem_label)

        # Log snippet
        snippet_text = QTextEdit()
        snippet_text.setReadOnly(True)
        snippet_text.setFont(QFont("Monospace", 10))
        snippet_text.setPlainText(issue.get("log_snippet", "No log snippet available"))
        snippet_text.setMinimumHeight(150)
        layout.addWidget(snippet_text)

        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)


class IssueWidget(QFrame):
    """Widget displaying a single issue with remediation option."""

    fix_this_clicked = pyqtSignal(dict)  # Signal to send issue to chatbot

    def __init__(self, issue: dict, parent=None):
        super().__init__(parent)
        self.issue = issue
        self.setup_ui()

    def setup_ui(self):
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Raised)
        self.setLineWidth(1)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Severity indicator with new levels
        severity = self.issue.get("severity", "mild")
        severity_colors = {
            "urgent": "#dc3545",    # Red
            "moderate": "#fd7e14",  # Orange
            "mild": "#0d6efd",      # Blue
            # Legacy support
            "critical": "#dc3545",
            "warning": "#fd7e14",
            "notice": "#0d6efd"
        }
        color = severity_colors.get(severity, "#6c757d")

        # Header with severity badge
        header = QLabel(f"<span style='background-color: {color}; color: white; padding: 2px 8px; border-radius: 3px; font-weight: bold;'>{severity.upper()}</span> {self.issue.get('problem', 'Unknown issue')}")
        header.setWordWrap(True)
        layout.addWidget(header)

        # Details
        if details := self.issue.get("details"):
            details_label = QLabel(details)
            details_label.setWordWrap(True)
            details_label.setStyleSheet("color: #666666; font-size: 11px; margin-left: 10px;")
            layout.addWidget(details_label)

        # Remediation
        if remediation := self.issue.get("remediation"):
            rem_frame = QFrame()
            rem_frame.setStyleSheet("background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 4px;")
            rem_layout = QVBoxLayout(rem_frame)
            rem_layout.setContentsMargins(8, 8, 8, 8)

            rem_label = QLabel("<b>Suggested Remediation:</b>")
            rem_layout.addWidget(rem_label)

            rem_text = QLabel(remediation)
            rem_text.setWordWrap(True)
            rem_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            rem_text.setFont(QFont("Monospace", 9))
            rem_layout.addWidget(rem_text)

            layout.addWidget(rem_frame)

        # Action buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        # See Log Snippet button
        if self.issue.get("log_snippet"):
            snippet_btn = QPushButton("See Log Snippet")
            snippet_btn.clicked.connect(self.show_log_snippet)
            snippet_btn.setStyleSheet("background-color: #6c757d; color: white; padding: 5px 10px;")
            btn_layout.addWidget(snippet_btn)

        # Fix This button (sends to chatbot)
        fix_btn = QPushButton("Fix This")
        fix_btn.clicked.connect(lambda: self.fix_this_clicked.emit(self.issue))
        fix_btn.setStyleSheet("background-color: #0d6efd; color: white; padding: 5px 10px;")
        btn_layout.addWidget(fix_btn)

        if self.issue.get("safe_to_auto_run", False):
            run_btn = QPushButton("Run Fix")
            run_btn.clicked.connect(self.run_remediation)
            run_btn.setStyleSheet("background-color: #198754; color: white; padding: 5px 10px;")
            btn_layout.addWidget(run_btn)

        copy_btn = QPushButton("Copy Command")
        copy_btn.clicked.connect(self.copy_remediation)
        copy_btn.setStyleSheet("padding: 5px 10px;")
        btn_layout.addWidget(copy_btn)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def show_log_snippet(self):
        """Show dialog with log snippet."""
        dialog = LogSnippetDialog(self.issue, self)
        dialog.exec()

    def run_remediation(self):
        """Execute remediation command after confirmation."""
        remediation = self.issue.get("remediation", "")

        # Confirmation dialog
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Confirm Remediation")
        msg.setText("Are you sure you want to run this command?")
        msg.setInformativeText(remediation)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)

        if msg.exec() == QMessageBox.StandardButton.Yes:
            try:
                # Run command
                result = subprocess.run(
                    remediation,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                # Show result
                result_msg = QMessageBox()
                if result.returncode == 0:
                    result_msg.setIcon(QMessageBox.Icon.Information)
                    result_msg.setWindowTitle("Success")
                    result_msg.setText("Command executed successfully")
                    if result.stdout:
                        result_msg.setDetailedText(result.stdout)
                else:
                    result_msg.setIcon(QMessageBox.Icon.Warning)
                    result_msg.setWindowTitle("Command Failed")
                    result_msg.setText(f"Exit code: {result.returncode}")
                    result_msg.setDetailedText(result.stderr or result.stdout)

                result_msg.exec()

            except subprocess.TimeoutExpired:
                QMessageBox.warning(self, "Timeout", "Command timed out after 30 seconds")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to run command: {e}")

    def copy_remediation(self):
        """Copy remediation command to clipboard."""
        remediation = self.issue.get("remediation", "")
        clipboard = QApplication.clipboard()
        clipboard.setText(remediation)

        # Brief feedback
        QMessageBox.information(self, "Copied", "Command copied to clipboard")


class LogViewerDialog(QDialog):
    """Dialog for viewing full boot logs."""

    def __init__(self, log_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Boot Logs")
        self.resize(900, 700)

        layout = QVBoxLayout(self)

        # Log text area
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("Monospace", 9))

        # Load log content
        try:
            log_content = Path(log_path).read_text()
            self.text_edit.setPlainText(log_content)
        except Exception as e:
            self.text_edit.setPlainText(f"Error loading logs: {e}")

        layout.addWidget(self.text_edit)

        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)


class SettingsDialog(QDialog):
    """Dialog for configuring application settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(500, 200)

        layout = QVBoxLayout(self)

        # API Key section
        api_label = QLabel("<b>OpenRouter API Key</b>")
        layout.addWidget(api_label)

        help_label = QLabel("Get your API key from <a href='https://openrouter.ai/keys'>openrouter.ai/keys</a>")
        help_label.setOpenExternalLinks(True)
        help_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(help_label)

        # API key input
        key_layout = QHBoxLayout()
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("sk-or-v1-...")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)

        # Load current key
        current_key = get_api_key()
        if current_key:
            self.api_key_input.setText(current_key)

        key_layout.addWidget(self.api_key_input)

        # Toggle visibility button
        show_btn = QPushButton("Show")
        show_btn.setCheckable(True)
        show_btn.toggled.connect(self.toggle_key_visibility)
        key_layout.addWidget(show_btn)

        layout.addLayout(key_layout)

        layout.addStretch()

        # Buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.save_settings)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def toggle_key_visibility(self, checked: bool):
        """Toggle API key visibility."""
        if checked:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)

    def save_settings(self):
        """Save settings and close dialog."""
        api_key = self.api_key_input.text().strip()
        save_api_key(api_key)
        QMessageBox.information(self, "Settings Saved", "API key saved successfully.")
        self.accept()


class ChatPanel(QWidget):
    """Chat panel for interactive remediation assistance."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.log_content = ""
        self.current_issue = None
        self.conversation_history = []
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QLabel("<h3>AI Assistant</h3>")
        layout.addWidget(header)

        # Chat history display
        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setFont(QFont("Sans", 10))
        self.chat_display.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.chat_display, 1)

        # Input area
        input_layout = QHBoxLayout()

        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Ask about the issue or request help...")
        self.chat_input.returnPressed.connect(self.send_message)
        self.chat_input.setStyleSheet("padding: 8px; border: 1px solid #dee2e6; border-radius: 4px;")
        input_layout.addWidget(self.chat_input)

        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self.send_message)
        send_btn.setStyleSheet("background-color: #0d6efd; color: white; padding: 8px 16px;")
        input_layout.addWidget(send_btn)

        layout.addLayout(input_layout)

        # Clear button
        clear_btn = QPushButton("Clear Chat")
        clear_btn.clicked.connect(self.clear_chat)
        clear_btn.setStyleSheet("padding: 5px;")
        layout.addWidget(clear_btn)

        # Initial message
        self.add_message("assistant", "I have access to your boot logs. Click 'Fix This' on any issue, or ask me questions about your system.")

    def set_log_content(self, content: str):
        """Set the log content for context."""
        self.log_content = content

    def focus_on_issue(self, issue: dict):
        """Focus chat on a specific issue."""
        self.current_issue = issue
        problem = issue.get("problem", "this issue")
        severity = issue.get("severity", "unknown")

        # Add a system message about the focus
        self.add_message("system", f"Now focusing on: [{severity.upper()}] {problem}")

        # Auto-send initial question
        initial_msg = f"Please help me fix this issue: {problem}\n\nThe suggested remediation is: {issue.get('remediation', 'N/A')}\n\nCan you explain what this does and if it's safe to run? Are there any alternatives?"

        self.add_message("user", initial_msg)
        self.conversation_history.append({"role": "user", "content": initial_msg})

        # Get AI response
        self.get_ai_response(initial_msg)

    def send_message(self):
        """Send user message to AI."""
        message = self.chat_input.text().strip()
        if not message:
            return

        self.chat_input.clear()
        self.add_message("user", message)
        self.conversation_history.append({"role": "user", "content": message})

        self.get_ai_response(message)

    def get_ai_response(self, message: str):
        """Get AI response in background."""
        self.chat_input.setEnabled(False)

        self.worker = ChatWorker(
            message,
            self.log_content,
            self.current_issue,
            self.conversation_history[:-1]  # Exclude the message we just added
        )
        self.worker.finished.connect(self.on_response_received)
        self.worker.error.connect(self.on_response_error)
        self.worker.start()

    def on_response_received(self, response: str):
        """Handle AI response."""
        self.add_message("assistant", response)
        self.conversation_history.append({"role": "assistant", "content": response})
        self.chat_input.setEnabled(True)
        self.chat_input.setFocus()

    def on_response_error(self, error: str):
        """Handle response error."""
        self.add_message("error", f"Error: {error}")
        self.chat_input.setEnabled(True)

    def markdown_to_html(self, text: str) -> str:
        """Convert basic markdown to HTML."""
        # Escape HTML first
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # Code blocks (```...```)
        def replace_code_block(match):
            code = match.group(1)
            return f"<pre style='background-color: #e9ecef; padding: 8px; border-radius: 4px; font-family: monospace; overflow-x: auto;'>{code}</pre>"

        text = re.sub(r'```(?:\w+)?\n?(.*?)```', replace_code_block, text, flags=re.DOTALL)

        # Inline code (`...`)
        text = re.sub(r'`([^`]+)`', r"<code style='background-color: #e9ecef; padding: 2px 4px; border-radius: 3px; font-family: monospace;'>\1</code>", text)

        # Bold (**...**)
        text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)

        # Italic (*...*)
        text = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', text)

        # Headers (### ... )
        text = re.sub(r'^### (.+)$', r'<b style="font-size: 14px;">\1</b>', text, flags=re.MULTILINE)
        text = re.sub(r'^## (.+)$', r'<b style="font-size: 15px;">\1</b>', text, flags=re.MULTILINE)
        text = re.sub(r'^# (.+)$', r'<b style="font-size: 16px;">\1</b>', text, flags=re.MULTILINE)

        # Bullet lists (- item)
        text = re.sub(r'^- (.+)$', r'&bull; \1', text, flags=re.MULTILINE)

        # Numbered lists (1. item) - simple version
        text = re.sub(r'^(\d+)\. (.+)$', r'\1. \2', text, flags=re.MULTILINE)

        # Line breaks
        text = text.replace("\n", "<br>")

        return text

    def add_message(self, role: str, content: str):
        """Add a message to the chat display."""
        colors = {
            "user": "#0d6efd",
            "assistant": "#198754",
            "system": "#6c757d",
            "error": "#dc3545"
        }
        labels = {
            "user": "You",
            "assistant": "AI Assistant",
            "system": "System",
            "error": "Error"
        }

        color = colors.get(role, "#000000")
        label = labels.get(role, role.title())

        # Convert markdown to HTML for assistant messages
        if role == "assistant":
            formatted_content = self.markdown_to_html(content)
        else:
            # For user/system messages, just escape and convert newlines
            formatted_content = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            formatted_content = formatted_content.replace("\n", "<br>")

        html = f"""
        <div style='margin-bottom: 10px;'>
            <span style='color: {color}; font-weight: bold;'>{label}:</span><br>
            <div style='margin-left: 10px; margin-top: 4px;'>{formatted_content}</div>
        </div>
        """

        cursor = self.chat_display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.chat_display.setTextCursor(cursor)
        self.chat_display.insertHtml(html)
        self.chat_display.insertPlainText("\n")

        # Scroll to bottom
        scrollbar = self.chat_display.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_chat(self):
        """Clear chat history."""
        self.chat_display.clear()
        self.conversation_history = []
        self.current_issue = None
        self.add_message("assistant", "Chat cleared. I still have access to your boot logs. How can I help?")


class MainWindow(QMainWindow):
    """Main application window with two-panel layout."""

    def __init__(self):
        super().__init__()
        self.log_path = None
        self.log_content = ""
        self.setup_ui()
        self.start_analysis()

    def setup_ui(self):
        self.setWindowTitle("Ubuntu Boot Monitoring Agent")
        self.setMinimumSize(1200, 700)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Header
        header_layout = QHBoxLayout()
        header = QLabel("<h2>Boot Log Analysis</h2>")
        header_layout.addWidget(header)
        header_layout.addStretch()

        # Top buttons
        self.view_logs_btn = QPushButton("View Full Logs")
        self.view_logs_btn.clicked.connect(self.view_logs)
        self.view_logs_btn.setEnabled(False)
        header_layout.addWidget(self.view_logs_btn)

        refresh_btn = QPushButton("Re-analyze")
        refresh_btn.clicked.connect(self.start_analysis)
        header_layout.addWidget(refresh_btn)

        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self.show_settings)
        header_layout.addWidget(settings_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        header_layout.addWidget(close_btn)

        main_layout.addLayout(header_layout)

        # Status and summary
        self.status_label = QLabel("Analyzing boot logs...")
        main_layout.addWidget(self.status_label)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("margin-bottom: 10px;")
        main_layout.addWidget(self.summary_label)

        # Two-panel splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel - Issues
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        issues_header = QLabel("<h3>Issues Found</h3>")
        left_layout.addWidget(issues_header)

        # Scroll area for issues
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: 1px solid #dee2e6; }")

        self.issues_container = QWidget()
        self.issues_layout = QVBoxLayout(self.issues_container)
        self.issues_layout.addStretch()

        scroll.setWidget(self.issues_container)
        left_layout.addWidget(scroll, 1)

        splitter.addWidget(left_panel)

        # Right panel - Chat
        self.chat_panel = ChatPanel()
        splitter.addWidget(self.chat_panel)

        # Set splitter proportions (60% issues, 40% chat)
        splitter.setSizes([600, 400])

        main_layout.addWidget(splitter, 1)

    def start_analysis(self):
        """Start background log analysis."""
        self.status_label.setText("Analyzing boot logs...")
        self.status_label.setStyleSheet("")
        self.summary_label.setText("")

        # Clear previous issues
        while self.issues_layout.count() > 1:
            item = self.issues_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Start worker
        self.worker = AnalysisWorker()
        self.worker.finished.connect(self.on_analysis_complete)
        self.worker.error.connect(self.on_analysis_error)
        self.worker.start()

    def on_analysis_complete(self, results: dict, log_path: str, log_content: str):
        """Handle completed analysis."""
        self.log_path = log_path
        self.log_content = log_content
        self.view_logs_btn.setEnabled(True)

        # Pass log content to chat panel
        self.chat_panel.set_log_content(log_content)

        issues = results.get("issues", [])
        summary = results.get("summary", "Analysis complete")

        if not issues:
            self.status_label.setText("No issues detected")
            self.status_label.setStyleSheet("color: #198754; font-weight: bold;")
        else:
            # Count by severity
            urgent = sum(1 for i in issues if i.get("severity") in ["urgent", "critical"])
            moderate = sum(1 for i in issues if i.get("severity") in ["moderate", "warning"])
            mild = sum(1 for i in issues if i.get("severity") in ["mild", "notice"])

            status_parts = []
            if urgent:
                status_parts.append(f"{urgent} urgent")
            if moderate:
                status_parts.append(f"{moderate} moderate")
            if mild:
                status_parts.append(f"{mild} mild")

            self.status_label.setText(f"Found {len(issues)} issue(s): {', '.join(status_parts)}")

            if urgent:
                self.status_label.setStyleSheet("color: #dc3545; font-weight: bold;")
            elif moderate:
                self.status_label.setStyleSheet("color: #fd7e14; font-weight: bold;")
            else:
                self.status_label.setStyleSheet("color: #0d6efd; font-weight: bold;")

        self.summary_label.setText(summary)

        # Add issue widgets
        for issue in issues:
            widget = IssueWidget(issue)
            widget.fix_this_clicked.connect(self.chat_panel.focus_on_issue)
            self.issues_layout.insertWidget(self.issues_layout.count() - 1, widget)

    def on_analysis_error(self, error: str):
        """Handle analysis error."""
        self.status_label.setText("Analysis failed")
        self.status_label.setStyleSheet("color: #dc3545; font-weight: bold;")
        self.summary_label.setText(f"Error: {error}")

    def view_logs(self):
        """Show log viewer dialog."""
        if self.log_path:
            dialog = LogViewerDialog(self.log_path, self)
            dialog.exec()

    def show_settings(self):
        """Show settings dialog."""
        dialog = SettingsDialog(self)
        dialog.exec()


def main():
    """Main entry point for GUI."""
    app = QApplication(sys.argv)
    app.setApplicationName("Ubuntu Boot Monitoring Agent")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

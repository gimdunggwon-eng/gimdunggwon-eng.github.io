import shutil
import subprocess


class DesktopEngine:
    """Opens only explicitly allowlisted built-in applications."""

    APPLICATIONS = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
    }

    def open_application(self, application_id: str) -> None:
        executable = self.APPLICATIONS.get(application_id.strip().lower())
        if executable is None:
            raise ValueError("Application is not on the allowlist")
        resolved = shutil.which(executable)
        if resolved is None:
            raise FileNotFoundError(f"{executable} is not available on this system")
        subprocess.Popen([resolved], shell=False, close_fds=True)

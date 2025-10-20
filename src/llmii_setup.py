import sys
import os
import json
import subprocess
import re
from pathlib import Path
import platform
import requests
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QDialog, QVBoxLayout, QHBoxLayout, 
    QLabel, QRadioButton, QPushButton, QProgressBar, QMessageBox,
    QScrollArea, QWidget, QGroupBox, QFrame, QSizePolicy, QSpacerItem,
    QMenuBar, QButtonGroup
    )
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon

from src.config import RESOURCES_DIR


# GPU detection logic adapted from koboldcpp.py, by Concedo:
# https://github.com/LostRuins/koboldcpp/blob/6888f5495d2839b0f590f200299520fa2c156b33/koboldcpp.py#L923C1-L923C48
# March 24, 2025
 
class GpuDetector:
    """Class for detecting GPU capabilities and appropriate backend"""
    
    def __init__(self):
        self.summary = {
            "cuda_available": False,
            "cuda_version": None,
            "vulkan_available": False,
            "opencl_available": False,
            "total_vram_mb": 0,
            "recommended_backend": "CPU"
        }
    
    def detect_nvidia_gpu(self):
        """Detect NVIDIA GPU and CUDA capabilities"""
        try:
            # Check for CUDA version
            output = subprocess.run(
                ['nvidia-smi', '-q', '-d=compute'], 
                capture_output=True, text=True, check=True, encoding='utf-8'
            ).stdout
            
            for line in output.splitlines():
                if line.strip().startswith('CUDA'):
                    self.summary["cuda_version"] = line.split()[3]
                    self.summary["cuda_available"] = True
            
            # Get VRAM information
            output = subprocess.run(
                ['nvidia-smi', '--query-gpu=memory.total', '--format=csv,noheader'], 
                capture_output=True, text=True, check=True, encoding='utf-8'
            ).stdout
            
            vram_mb = int(output.strip().split()[0])
            self.summary["total_vram_mb"] = vram_mb
            
            return True
        except Exception as e:
            print(f"No NVIDIA GPU detected: {e}")
            return False
    
    def detect_vulkan(self):
        """Detect Vulkan-compatible GPUs and their VRAM"""
        try:
            output = subprocess.run(
                ['vulkaninfo', '--summary'], 
                capture_output=True, text=True, check=True, encoding='utf-8'
            ).stdout
            
            if "deviceName" in output:
                self.summary["vulkan_available"] = True
                
                # Parse device names
                vulkan_devices = []
                device_names = []
                device_types = []
                
                for line in output.splitlines():
                    if "deviceName" in line:
                        name = line.split("=")[1].strip()
                        device_names.append(name)
                    if "deviceType" in line:
                        device_type = line.split("=")[1].strip()
                        is_discrete = "DISCRETE" in device_type
                        device_types.append(is_discrete)
                
                vram_sizes = []
                for line in output.splitlines():
                    if "VkPhysicalDeviceMemoryProperties" in line or "heapSize" in line:
                        # Look for memory heap sizes, typically in bytes
                        if "heapSize" in line and "0x" in line:  # Hex value
                            try:
                                # Extract hex value and convert to bytes
                                hex_value = line.split("0x")[1].split()[0]
                                bytes_value = int(hex_value, 16)
                                mb_value = bytes_value / (1024 * 1024)
                                vram_sizes.append(int(mb_value))
                            except Exception:
                                pass
                
                for i in range(len(device_names)):
                    device = {
                        "name": device_names[i],
                        "is_discrete": device_types[i] if i < len(device_types) else False
                    }
                    
                    if i < len(vram_sizes):
                        device["vram_mb"] = vram_sizes[i]
                        # Update total VRAM if this is larger
                        if vram_sizes[i] > self.summary["total_vram_mb"]:
                            self.summary["total_vram_mb"] = vram_sizes[i]
                    
                    vulkan_devices.append(device)
                
                self.summary["vulkan_devices"] = vulkan_devices
                return True
            return False
        except Exception as e:
            print(f"No Vulkan support detected: {e}")
            return False
    
    def detect_amd_gpu(self):
        """Detect AMD GPUs and their VRAM using ROCm tools"""
        try:
            # Try rocminfo first
            output = subprocess.run(
                ['rocminfo'], 
                capture_output=True, text=True, check=True, encoding='utf-8'
            ).stdout
            
            amd_devices = []
            current_device = None
            
            for line in output.splitlines():
                line = line.strip()
                if "Marketing Name:" in line:
                    name = line.split(":", 1)[1].strip()
                    current_device = {"name": name}
                elif "Device Type:" in line and "GPU" in line and current_device:
                    # Current device is a GPU, keep it
                    amd_devices.append(current_device)
                    current_device = None
                elif "Device Type:" in line and "GPU" not in line:
                    # Not a GPU, discard
                    current_device = None
            
            # If we found AMD GPUs, try to get their VRAM
            if amd_devices:
                try:
                    vram_info = subprocess.run(
                        ['rocm-smi', '--showmeminfo', 'vram', '--csv'], 
                        capture_output=True, text=True, check=True, encoding='utf-8'
                    ).stdout
                    
                    # Parse CSV output for VRAM values
                    lines = vram_info.splitlines()
                    if len(lines) > 1:  # Skip header
                        for i, line in enumerate(lines[1:]):
                            if i < len(amd_devices) and "," in line:
                                try:
                                    vram_mb = int(line.split(",")[1].strip())
                                    amd_devices[i]["vram_mb"] = vram_mb
                                    
                                    # Update total VRAM if this is larger
                                    if vram_mb > self.summary["total_vram_mb"]:
                                        self.summary["total_vram_mb"] = vram_mb
                                except Exception:
                                    pass
                except Exception as e:
                    print(f"Error getting AMD VRAM: {e}")
            
            if amd_devices:
                self.summary["amd_available"] = True
                self.summary["amd_devices"] = amd_devices
                return True
            return False
        except Exception as e:
            print(f"No AMD GPU detected: {e}")
            return False

    def detect_all(self):
        """Detect all GPU capabilities and determine recommended backend"""

        self.summary["vulkan_devices"] = []
        self.summary["amd_devices"] = []
        
        # Try detecting in order of preference
        nvidia_detected = self.detect_nvidia_gpu()
        amd_detected = self.detect_amd_gpu()
        vulkan_detected = self.detect_vulkan()
        
        if nvidia_detected and self.summary["total_vram_mb"] >= 3500:
            self.summary["recommended_backend"] = "CUDA"
        elif amd_detected and self.summary["total_vram_mb"] >= 3500:
            self.summary["recommended_backend"] = "ROCm"
        elif vulkan_detected and self.summary["total_vram_mb"] >= 3500:
            self.summary["recommended_backend"] = "Vulkan"
        else:
            self.summary["recommended_backend"] = "CPU"
        
        print("GPU Detection Summary:")
        print(f"  NVIDIA GPU detected: {nvidia_detected}")
        print(f"  AMD GPU detected: {amd_detected}")
        print(f"  Vulkan available: {vulkan_detected}")
        print(f"  Total VRAM: {self.summary['total_vram_mb']} MB")
        print(f"  Recommended backend: {self.summary['recommended_backend']}")
        
        return self.summary


def is_display_available():
    """Try to create a QT application to test for display presence"""
    try:
        
        if os.name != 'nt' and not os.environ.get('DISPLAY'):
            return False
        
        from PyQt6.QtWidgets import QApplication
        import sys
        
        if QApplication.instance() is not None:
            return True
            
        test_app = QApplication(sys.argv)
        test_app.quit()
        return True
        
    except Exception as e:
        print(f"No display. Proceeding in terminal: {e}")
        return False


def download_file(url, destination):
    """
    Downloads a file from the specified URL to the destination path.
    
    Returns True if successful
    """
    try:
        print(f"Downloading from {url}...")
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        block_size = 1024
        downloaded = 0
        
        with open(destination, 'wb') as file:
            for data in response.iter_content(block_size):
                downloaded += len(data)
                file.write(data)
                
                if total_size > 0:
                    progress = int(50 * downloaded / total_size)
                    sys.stdout.write(f"\r[{'=' * progress}{' ' * (50 - progress)}] {downloaded}/{total_size} bytes")
                    sys.stdout.flush()
        
        if total_size > 0:
            sys.stdout.write('\n')
        
        print(f"Download completed: {destination}")
        return True
    except Exception as e:
        print(f"Error downloading file: {e}")
        if os.path.exists(destination):
            os.remove(destination)
        return False

def get_kobold_version(executable_path):
    """
    Gets the version of the Kobold executable by running it with --version flag.
    
    Parameters:
        executable_path (str): Path to the Kobold executable
    
    Returns:
        str: Version number or None if failed
    """
    try:
        # Make the file executable on Unix-like systems
        if not os.name == 'nt':
            os.chmod(executable_path, 0o755)
            
        result = subprocess.run([executable_path, '--version'], 
                              capture_output=True, text=True, check=True)
        version_output = result.stdout.strip()
        print (version_output)
        # Extract version number
        version_match = re.search(r'(\d+(?:\.\d+)*)', version_output)
        if version_match:
            return version_match.group(1)
    except Exception as e:
        print(f"Error getting Kobold version: {e}")
    
    return None

def sanitize_version(version):
    """
    Sanitizes version string to be compatible with filenames across platforms.
    
    Parameters:
        version (str): Version string
    
    Returns:
        str: Sanitized version string
    """
    return version.replace('.', '_')

def determine_kobold_filename(gpu_summary):
    """
    Determines which KoboldCPP executable to download based on system and GPU detection.
    
    Returns:
        str: Filename to download
    """
    system = platform.system()
    summary = gpu_summary
    
    # Check if CUDA is available and get its version
    cuda_available = summary["cuda_available"]
    cuda_version = summary["cuda_version"]
    
    if system == "Windows":
        #if cuda_available:
        #    major_version = float(cuda_version.split('.')[0])
        #    if major_version >= 12:
        return "koboldcpp.exe"
        #    else:
        #        return "koboldcpp.exe"
        #else:
            #return "koboldcpp_nocuda.exe"
    
    elif system == "Darwin":  # macOS
        if platform.machine() == "arm64":
            return "koboldcpp-mac-arm64"
        else:
            return None
    
    elif system == "Linux":
        if cuda_available:
            major_version = float(cuda_version.split('.')[0])
            if major_version >= 12:
                return "koboldcpp-linux-x64"
            else:
                return "koboldcpp-linux-x64-oldpc"
        else:
            return "koboldcpp-linux-x64-nocuda"
    
    else:
        raise ValueError(f"Unsupported operating system: {system}")

def manage_kobold_executable():
    """
    Manages the Kobold executable by checking for updates and downloading if needed.
    
    Returns:
        str: Path to the Kobold executable to run
    """
    

    os.makedirs(RESOURCES_DIR, exist_ok=True)
    
    version_file = os.path.join(RESOURCES_DIR, "version.txt")
    current_version = None
    
    # Check for version.txt file
    if os.path.exists(version_file):
        with open(version_file, 'r') as f:
            current_version = f.read().strip()
    
    existing_executable = None
    executable_version = None
    for file in os.listdir(RESOURCES_DIR):
        if file.startswith("koboldcpp-"):
            existing_executable = os.path.join(RESOURCES_DIR, file)
            match = re.search(r'koboldcpp-([^\.]+)', file)
            if match:
                executable_version = match.group(1).replace('_', '.')
            break
    return existing_executable
    
def download_kobold(gpu_summary, existing_executable):
    print("Checking for KoboldCpp update...")
    base_url = "https://github.com/LostRuins/koboldcpp/releases/latest/download/"
    version_file = os.path.join(RESOURCES_DIR, "version.txt")
    download_filename = determine_kobold_filename(gpu_summary)
    download_url = base_url + download_filename
    
    extension = '.exe' if download_filename.endswith('.exe') else ''
    temp_download_path = os.path.join(RESOURCES_DIR, download_filename)
    if download_file(download_url, temp_download_path):
        version = get_kobold_version(temp_download_path)
        if version:
            with open(version_file, 'w') as f:
                f.write(version)
            
            sanitized_version = sanitize_version(version)
            final_path = os.path.join(RESOURCES_DIR, f"koboldcpp-{sanitized_version}{extension}")
            
            if existing_executable and os.path.exists(existing_executable):
                os.remove(existing_executable)
            
            os.rename(temp_download_path, final_path)
            
            print(f"Successfully downloaded and installed Kobold version {version}")
            return final_path
        else:
            print("Failed to get version information from downloaded executable")
            return temp_download_path
    else:
        print("Failed to download Kobold executable")
        if existing_executable:
            print(f"Using existing executable: {existing_executable}")
            return existing_executable
        else:
            raise FileNotFoundError("No Kobold executable available")


def list_models_terminal():
    """List available models in terminal mode"""
    model_list_path = os.path.join(RESOURCES_DIR, "model_list.json")
    try:
        with open(model_list_path, "r") as file:
            models = json.load(file)
        
        print("Available models:")
        for model in models:
            print(f"  {model['model']}")
            print(f"    Description: {model['description']}")
            print(f"    Size: {model['size_mb']} MB")
            print()
    except Exception as e:
        print(f"Error loading models: {e}")
        return 1

def run_detection_terminal():
    """Run GPU detection in terminal mode"""
    detector = GpuDetector()
    gpu_summary = detector.detect_all()
    return 0

def setup_koboldcpp_terminal(model, gpu_summary):
    """Terminal version of setup_koboldcpp without Qt dependencies"""
    executable_path = gpu_summary["executable_path"]
    full_command_path = os.path.join(RESOURCES_DIR, "kobold_command.txt")
    args_path = os.path.join(RESOURCES_DIR, "kobold_args.json")
    
    kobold_args = {
        "executable": os.path.basename(executable_path),
        "model_param": model["language_url"],
        "mmproj": model["mmproj_url"],
        "flashattention": "",
        "contextsize": "4096",
        "visionmaxres": "9999",
        "chatcompletionsadapter": model["adapter"]
    }
    
    full_command = f"{executable_path} {kobold_args['model_param']} --mmproj {kobold_args['mmproj']} --flashattention --contextsize {kobold_args['contextsize']} --visionmaxres 9999 --chatcompletionsadapter {kobold_args['chatcompletionsadapter']}"
    
    try:
        with open(full_command_path, "w") as f:
            f.write(full_command)
        
        with open(args_path, "w") as f:
            json.dump(kobold_args, f, indent=4)
        
        return True
        
    except Exception as e:
        print(f"Failed to create configuration: {e}")
        return False

def setup_terminal(update=False, model_name=None):
    """Run setup in terminal mode"""
    print("Running in terminal mode (no display detected)")
    print("=" * 50)
    
    model_list_path = os.path.join(RESOURCES_DIR, "model_list.json")
    try:
        with open(model_list_path, "r") as file:
            models = json.load(file)
    except Exception as e:
        print(f"Error loading models: {e}")
        return 1
    
    print("Detecting GPU capabilities...")
    detector = GpuDetector()
    gpu_summary = detector.detect_all()
    print()
    
    existing_executable = manage_kobold_executable()
    if update or not existing_executable:
        print("Getting KoboldCPP executable...")
        try:
            gpu_summary["executable_path"] = download_kobold(gpu_summary, existing_executable)
        except Exception as e:
            print(f"Failed to download executable: {e}")
            if existing_executable:
                print(f"Using existing executable: {existing_executable}")
                gpu_summary["executable_path"] = existing_executable
            else:
                return 1
    else:
        gpu_summary["executable_path"] = existing_executable
        print(f"Using existing executable: {existing_executable}")
    
    print()
    
    selected_model = None
    if model_name:
        for model in models:
            if model["model"].lower() == model_name.lower():
                selected_model = model
                break
        if not selected_model:
            print(f"Model '{model_name}' not found.")
            print("\nAvailable models:")
            for model in models:
                print(f"  - {model['model']}: {model['description']} ({model['size_mb']} MB)")
            return 1
    else:
        print("Available models:")
        for i, model in enumerate(models):
            fits_vram = (gpu_summary["recommended_backend"] == "CPU" or 
                        model["size_mb"] <= gpu_summary["total_vram_mb"])
            
            status = "✓ Recommended" if fits_vram else "⚠ May exceed VRAM"
            print(f"  {i+1}. {model['model']}: {model['description']}")
            print(f"     Size: {model['size_mb']} MB - {status}")
            print()
        
        while True:
            try:
                choice = input(f"Select a model (1-{len(models)}): ").strip()
                if choice.lower() in ['q', 'quit', 'exit']:
                    print("Setup cancelled.")
                    return 1
                
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(models):
                    selected_model = models[choice_idx]
                    break
                else:
                    print(f"Please enter a number between 1 and {len(models)}")
            except ValueError:
                print("Please enter a valid number (or 'q' to quit)")
            except KeyboardInterrupt:
                print("\nSetup cancelled.")
                return 1
        
        print(f"Selected: {selected_model['model']}")
    
    print()
    
    print("Creating configuration...")
    success = setup_koboldcpp_terminal(selected_model, gpu_summary)
    
    if success:
        print("Setup completed successfully!")
        print(f"Configuration saved to: {RESOURCES_DIR}")
        return 0
    else:
        print("Setup failed")
        return 1

class ModelSelectionDialog:
    """Dialog for selecting a model based on available VRAM"""
    def __init__(self, models, gpu_summary, parent=None):
        
        self.dialog = QDialog(parent)
        self.models = models
        self.gpu_summary = gpu_summary
        self.selected_model = None
        
        self.dialog.setWindowTitle("Select AI Model")
        self.dialog.setMinimumWidth(600)
        self.dialog.setMinimumHeight(400)
        
        self.setup_ui()
        
    def setup_ui(self):
        
        layout = QVBoxLayout()
        
        header = QLabel(f"<h2>Select a Model for KoboldCPP</h2>")
        
        gpu_info_box = QGroupBox("GPU Information")
        gpu_info_layout = QVBoxLayout()
        
        if self.gpu_summary["recommended_backend"] != "CPU":    
            vram_info = QLabel(f"VRAM: {self.gpu_summary['total_vram_mb']} MB total")
            backend_info = QLabel(f"Recommended backend: {self.gpu_summary['recommended_backend']}")
            gpu_info_layout.addWidget(vram_info)
            gpu_info_layout.addWidget(backend_info)
        else:
            no_gpu_info = QLabel("No compatible GPU detected. Models will run on CPU only.")
            gpu_info_layout.addWidget(no_gpu_info)
            
        gpu_info_box.setLayout(gpu_info_layout)
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        model_container = QWidget()
        model_layout = QVBoxLayout()
        
        self.radio_buttons = []
        self.button_group = QButtonGroup(self.dialog)
        
        for i, model in enumerate(self.models):
            frame = QFrame()
            frame.setFrameShape(QFrame.Shape.StyledPanel)
            frame.setFrameShadow(QFrame.Shadow.Raised)
            
            model_item_layout = QVBoxLayout()
            
            header_layout = QHBoxLayout()
            radio = QRadioButton(model["model"])
            radio.setChecked(i == 0) 
            self.radio_buttons.append(radio)
            self.button_group.addButton(radio, i)
            
            header_layout.addWidget(radio)
            
            if (self.gpu_summary["recommended_backend"] != "CPU" and 
                model["size_mb"] > (self.gpu_summary["total_vram_mb"])):
                warning = QLabel("⚠️ May exceed available VRAM")
                warning.setStyleSheet("color: #FFA500;")
                header_layout.addWidget(warning)
                header_layout.addStretch()
            else:
                header_layout.addStretch()
            
            model_item_layout.addLayout(header_layout)
            
            desc = QLabel(model["description"])
            desc.setWordWrap(True)
            model_item_layout.addWidget(desc)
            
            size_info = QLabel(f"Size: {model['size_mb']} MB")
            size_info.setAlignment(Qt.AlignmentFlag.AlignRight)
            model_item_layout.addWidget(size_info)
            
            frame.setLayout(model_item_layout)
            model_layout.addWidget(frame)

        model_container.setLayout(model_layout)
        scroll_area.setWidget(model_container)
        
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.dialog.reject)
        
        select_button = QPushButton("Select")
        select_button.clicked.connect(self.accept_selection)
        select_button.setDefault(True)
        
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(select_button)
        
        layout.addWidget(header)
        layout.addWidget(gpu_info_box)
        layout.addWidget(QLabel("<b>Available Models:</b>"))
        layout.addWidget(scroll_area)
        layout.addSpacing(10)
        layout.addLayout(button_layout)
        
        self.dialog.setLayout(layout)
    
    def exec(self):
        return self.dialog.exec()
    
    def accept_selection(self):
        for i, radio in enumerate(self.radio_buttons):
            if radio.isChecked():
                self.selected_model = self.models[i]
                self.dialog.accept()
                break

class GuiLaunchThread:
    """Background thread for launching the GUI"""
    
    def run(self):
        
        thread = QThread()
        # llmii_gui.run_gui()
        
class SetupApp:
    """Main application logic"""
    
    def __init__(self):
        
        self.app = QApplication(sys.argv)
        self.app.setStyle("Fusion")  # Modern cross-platform style
        self.setup_theme()
        model_list_path = os.path.join(RESOURCES_DIR, "model_list.json")
        try:
            with open(model_list_path, "r") as file:
                self.models = json.load(file)
        except Exception as e:
            QMessageBox.critical(None, "Error", f"Could not load model list: {e}")
            sys.exit(1)
        
        self.detector = GpuDetector()
        
    def setup_theme(self):
        """Set up dark theme for the application"""
        
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
        palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
        palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
        
        self.app.setPalette(palette)
    
    def run_setup(self, update=True):
        
        """Run setup and detection process with progress dialog"""
        #progress_dialog = ProgressDialog()
        #progress_dialog.show()
        
        #progress_dialog.update_progress("Detecting GPU capabilities...", 10)
        gpu_summary = self.detector.detect_all()
        
        backend = gpu_summary["recommended_backend"]
        #progress_dialog.update_progress(f"Recommended backend: {backend}", 40)
        
        if gpu_summary["cuda_available"]:
            #progress_dialog.update_progress(
            #    f"CUDA {gpu_summary['cuda_version']} detected with {gpu_summary['total_vram_mb']}MB VRAM", 
            #    50
            #)
            print(f"CUDA {gpu_summary['cuda_version']} detected with {gpu_summary['total_vram_mb']}MB VRAM")
        existing_executable = manage_kobold_executable()
        
        if update:
            #progress_dialog.update_progress("Getting KoboldCPP executable...", 60)
            gpu_summary["executable_path"] = download_kobold(gpu_summary, existing_executable)
        
        else:
            gpu_summary["executable_path"] = existing_executable
        
        #progress_dialog.update_progress("Setup completed successfully", 100)
        
        QApplication.processEvents()
        
        # Wait a moment to show completion
        import time
        time.sleep(1)
        
        # Hide progress dialog
        #progress_dialog.accept()
        
        return gpu_summary
    
    def show_model_selection(self, gpu_summary):
        """Show model selection dialog"""
        
        dialog = ModelSelectionDialog(self.models, gpu_summary)
        
        if dialog.exec():
            selected_model = dialog.selected_model
            return selected_model
        return None
    
    def setup_koboldcpp(self, model, gpu_summary):
        """Create a KCPPS config file for the selected model and exit"""
        executable_path = gpu_summary["executable_path"]
        full_command_path = os.path.join(RESOURCES_DIR, "kobold_command.txt")
        args_path = os.path.join(RESOURCES_DIR, "kobold_args.json")
        
        kobold_args = {
            "executable": os.path.basename(executable_path),
            "model_param": model["language_url"],
            "mmproj": model["mmproj_url"],
            "flashattention": "",
            "contextsize": "4096",
            "visionmaxres": "9999",
            "chatcompletionsadapter": model["adapter"]
        }
        full_command = f"{executable_path} {kobold_args['model_param']} --mmproj {kobold_args['mmproj']} --contextsize {kobold_args['contextsize']} --visionmaxres 9999 --chatcompletionsadapter {kobold_args['chatcompletionsadapter']}" 
        
        try:
            with open(full_command_path, "w") as f:
                f.write(full_command)
            
            with open(args_path, "w") as f:
                json.dump(kobold_args, f, indent=4)
            
            print(f"Setup completed. Run commands located at: {args_path}")
            return 
            
        except Exception as e:
            QMessageBox.critical(None, "Error", f"Failed: {e}")
            return False
   
    def run(self, update=False):
        """Run the entire setup process"""
        try:
            
            gpu_summary = self.run_setup(update)
            
            selected_model = self.show_model_selection(gpu_summary)
            if not selected_model:
                print("Model selection cancelled.")
                return 1

            setup_success = self.setup_koboldcpp(selected_model, gpu_summary)
            if setup_success:
                QMessageBox.information(None, "Setup Complete", 
                    "Setup completed successfully. You can now run the application.")
                return 0
            else:
                return 1
                
        except Exception as e:
            QMessageBox.critical(None, "Error", f"An error occurred: {str(e)}")
            return 1


def setup(update=False):
    """Main setup function"""
    if is_display_available():
        
        setup_app = SetupApp()
        return setup_app.run(update)
    else:
        return setup_terminal(update)

    
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Setup Utility for LLMII")
    parser.add_argument("--update", action="store_true", help="Install or Update KoboldCpp executable")
    parser.add_argument("--force-terminal", action="store_true", help="Force terminal mode even if display available")
    parser.add_argument("--model", type=str, help="Specify model name for terminal mode")
    parser.add_argument("--detect-only", action="store_true", help="Only run GPU detection and exit")
    parser.add_argument("--list-models", action="store_true", help="List available models and exit")
    
    args = parser.parse_args()
    
    if args.list_models:
        list_models_terminal()
        return 0
    
    if args.detect_only:
        run_detection_terminal()
        return 0
    
    if args.force_terminal or not is_display_available():
        return setup_terminal(args.update, args.model)
    else:
        return setup(args.update)
    sys.exit()
if __name__ == "__main__":
    sys.exit(main())
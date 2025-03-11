#!/bin/bash

# Set the name of your virtual environment
VENV_NAME="llmii_env"

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check if Python is installed
if ! command_exists python3; then
    echo "Python 3 is not found. Please ensure Python 3 is installed and added to your PATH."
    exit 1
fi

# Check if exiftool is installed
if ! command_exists exiftool; then
    echo "exiftool is not found. Attempting to install..."
    
    # Try to install based on the OS
    if [[ "$(uname)" == "Darwin" ]]; then
        if command_exists brew; then
            echo "Installing exiftool using Homebrew..."
            brew install exiftool
        else
            echo "Homebrew not found. Please install Homebrew first, then run 'brew install exiftool'"
            exit 1
        fi
    elif [[ "$(uname)" == "Linux" ]]; then
        # Check for common package managers
        if command_exists apt-get; then
            echo "Installing exiftool using apt..."
            sudo apt-get update && sudo apt-get install -y libimage-exiftool-perl
        elif command_exists dnf; then
            echo "Installing exiftool using dnf..."
            sudo dnf install -y perl-Image-ExifTool
        elif command_exists yum; then
            echo "Installing exiftool using yum..."
            sudo yum install -y perl-Image-ExifTool
        elif command_exists pacman; then
            echo "Installing exiftool using pacman..."
            sudo pacman -S --noconfirm perl-image-exiftool
        else
            echo "Could not determine package manager. Please install exiftool manually."
            exit 1
        fi
    else
        echo "Unsupported operating system. Please install exiftool manually."
        exit 1
    fi
    
    # Check if installation was successful
    if ! command_exists exiftool; then
        echo "Failed to install exiftool. Please install it manually."
        exit 1
    else
        echo "exiftool has been installed successfully."
    fi
else
    echo "exiftool is already installed."
fi

# Check if the virtual environment exists, create if it doesn't
if [ ! -d "$VENV_NAME" ]; then
    echo "Creating new virtual environment: $VENV_NAME"
    python3 -m venv "$VENV_NAME"
    if [ $? -ne 0 ]; then
        echo "Failed to create virtual environment. Please check your Python installation."
        exit 1
    fi
else
    echo "Virtual environment $VENV_NAME already exists."
fi

# Activate the virtual environment
source "$VENV_NAME/bin/activate"

# Check if requirements.txt exists
if [ ! -f "requirements.txt" ]; then
    echo "requirements.txt not found. Please create a requirements.txt file in the same directory as this script."
    exit 1
fi

# Upgrade pip to the latest version
python3 -m pip install --upgrade pip

# Install packages from requirements.txt
echo "Installing packages from requirements.txt..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Failed to install some packages. Please check your internet connection and requirements.txt file."
    exit 1
fi

# Clear screen
clear

# Ask user if they want to start KoboldCPP
while true; do
    read -p "Start KoboldCpp inference engine and load Qwen2-VL 2B Model? [y/n]: " kobold_choice
    case $kobold_choice in
        [Yy]* ) start_kobold=true; break;;
        [Nn]* ) start_kobold=false; break;;
        * ) echo "Please answer y or n.";;
    esac
done

if [ "$start_kobold" = true ]; then
    TEXT_MODEL="https://huggingface.co/bartowski/Qwen2-VL-2B-Instruct-GGUF/blob/main/Qwen2-VL-2B-Instruct-Q6_K.gguf"
    IMAGE_PROJECTOR="https://huggingface.co/bartowski/Qwen2-VL-2B-Instruct-GGUF/blob/main/mmproj-Qwen2-VL-2B-Instruct-f16.gguf"
    
    # Determine the correct KoboldCPP binary based on the system
    if [[ "$(uname)" == "Darwin" ]]; then
        # KoboldCPP only supports ARM-based Macs (M1/M2/etc)
        if [[ "$(uname -m)" == "arm64" ]]; then
            KOBOLDCPP_BINARY="koboldcpp-mac-arm64"
        else
            echo "KoboldCPP only supports ARM-based Macs. Intel-based Macs are not supported."
            exit 1
        fi
    elif [[ "$(uname)" == "Linux" ]]; then
        KOBOLDCPP_BINARY="koboldcpp-linux-x64"
    else
        echo "Unsupported operating system. Please run on macOS (ARM) or Linux."
        exit 1
    fi
    
    # Check if the KoboldCPP binary exists and is executable
    if [ ! -x "./$KOBOLDCPP_BINARY" ]; then
        echo "KoboldCPP binary not found or not executable."
        
        # Ask if user wants to download it
        while true; do
            read -p "Do you want to download KoboldCPP? [y/n]: " download_choice
            case $download_choice in
                [Yy]* ) download_kobold=true; break;;
                [Nn]* ) echo "Cannot continue without KoboldCPP. Exiting."; exit 1;;
                * ) echo "Please answer y or n.";;
            esac
        done
        
        if [ "$download_kobold" = true ]; then
            echo "Downloading KoboldCPP for $(uname) $(uname -m)..."
            
            if [[ "$(uname)" == "Darwin" ]]; then
                # Only ARM Macs are supported
                if [[ "$(uname -m)" == "arm64" ]]; then
                    # For Mac ARM
                    curl -L -o koboldcpp-mac-arm64 https://github.com/LostRuins/koboldcpp/releases/latest/download/koboldcpp-macOS-arm64
                else
                    echo "KoboldCPP only supports ARM-based Macs. Intel-based Macs are not supported."
                    exit 1
                fi
            elif [[ "$(uname)" == "Linux" ]]; then
                # For Linux
                curl -L -o koboldcpp-linux-x64 https://github.com/LostRuins/koboldcpp/releases/latest/download/koboldcpp-linux-x86_64
            fi
            
            # Make the downloaded binary executable
            chmod +x ./$KOBOLDCPP_BINARY
            
            if [ ! -x "./$KOBOLDCPP_BINARY" ]; then
                echo "Failed to download or make executable the KoboldCPP binary. Please download it manually."
                exit 1
            fi
        fi
    fi
    
    # Run KoboldCPP in the background
    "./$KOBOLDCPP_BINARY" "$TEXT_MODEL" --mmproj "$IMAGE_PROJECTOR" --flashattention --contextsize 4096 --visionmaxres 9999 --chatcompletionsadapter autoguess &
    KOBOLD_PID=$!
    echo "KoboldCPP started with PID: $KOBOLD_PID"
fi

# Clear screen
clear
echo "Status will update here when indexing has been started..."

# Launch the Python GUI script
python3 llmii_gui.py

# Clean up KoboldCPP process if it was started
if [ "$start_kobold" = true ] && ps -p $KOBOLD_PID > /dev/null; then
    echo "Shutting down KoboldCPP..."
    kill $KOBOLD_PID
fi

# Deactivate the virtual environment when the GUI is closed
deactivate

# Wait for user input before closing
read -p "Press Enter to exit..."

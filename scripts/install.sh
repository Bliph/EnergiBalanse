#!/bin/bash

SYSTEM_NAME="shedder"

USER="johan"
GROUP="johan"

################################################################################
# Create directories
################################################################################

create_directory()
{
    if [ -e "$1" ]; then
        if [ ! -d "$1" ]; then
            echo " > $1 exists and is not a directory."
            return 1
        fi
    else
        sudo mkdir -v -p "$1"
        if [ $? -ne 0 ]; then
            echo " > Failed to create $1"
            return 1
        fi
    fi
    [ -n "$2" ] && sudo chown -R "$2" "$1"
    [ -n "$3" ] && sudo chmod -R "$3" "$1"
    echo " > $1"
    return 0
}

echo "Creating directories..."

# Application files
create_directory "/opt/jofo/$SYSTEM_NAME" "$USER:$GROUP"

# Configuration files
create_directory "/etc/opt/jofo/$SYSTEM_NAME" "$USER:$GROUP"

# Log files
create_directory "/var/log/jofo/$SYSTEM_NAME" "$USER:$GROUP"

echo "DONE"

################################################################################
# Creating virtual environment
################################################################################

echo "Creating virtual environment..."

python3 -m venv "/opt/jofo/$SYSTEM_NAME"

echo "Activating environment..."

source "/opt/jofo/$SYSTEM_NAME/bin/activate"

echo "DONE"

################################################################################
# Install Python modules
################################################################################

echo "Installing Python modules..."

pip3 install -r requirements.txt

echo "Deactivating environment..."
deactivate

echo "DONE"

################################################################################
# Copy application files
################################################################################

echo "Copying application files..."

cp -v -r "$SYSTEM_NAME/"* "/opt/jofo/$SYSTEM_NAME/"

echo "DONE"

echo "Copying configuration files..."

# Copy with interactive on config files
cp -i -r -v "conf/"* "/etc/opt/jofo/$SYSTEM_NAME"

echo "DONE"

################################################################################
# Set up dayly log rotate
################################################################################

echo "Configuring log rotate..."

# Copy with interactive on config files
sudo cp -i -v "scripts/$SYSTEM_NAME" "/etc/logrotate.d/"

################################################################################
# Install as service
################################################################################

echo "Installing as service..."

sudo cp -v "scripts/jofo-$SYSTEM_NAME.service" "/etc/systemd/system/"

sudo systemctl enable "jofo-$SYSTEM_NAME.service"

echo "DONE"

echo
echo "================================================================================"
echo "  Service 'jofo-$SYSTEM_NAME' is not started"
echo "  Please (re)start the service:"
echo "    'sudo systemctl restart jofo-$SYSTEM_NAME.service'"
echo "================================================================================"
echo
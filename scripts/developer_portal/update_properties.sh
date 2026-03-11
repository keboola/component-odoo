#!/usr/bin/env bash

set -e

COMPONENT_DIR="${1:?Usage: update_properties.sh <extractor|writer>}"

if [ -z "$KBC_DEVELOPERPORTAL_APP" ]; then
    echo "Error: KBC_DEVELOPERPORTAL_APP environment variable is not set."
    exit 1
fi

# Pull the latest version of the developer portal CLI Docker image
docker pull quay.io/keboola/developer-portal-cli-v2:latest

update_property() {
    local app_id="$1"
    local prop_name="$2"
    local file_path="$3"

    if [ ! -f "$file_path" ]; then
        echo "File '$file_path' not found. Skipping update for property '$prop_name' of application '$app_id'."
        return
    fi

    # shellcheck disable=SC2155
    local value=$(<"$file_path")

    echo "Updating $prop_name for $app_id"
    echo "$value"

    if [ -n "$value" ]; then
        docker run --rm \
            -e KBC_DEVELOPERPORTAL_USERNAME \
            -e KBC_DEVELOPERPORTAL_PASSWORD \
            quay.io/keboola/developer-portal-cli-v2:latest \
            update-app-property "$KBC_DEVELOPERPORTAL_VENDOR" "$app_id" "$prop_name" --value="$value"
        echo "Property $prop_name updated successfully for $app_id"
    else
        echo "$prop_name is empty for $app_id, skipping..."
    fi
}

APP_ID="$KBC_DEVELOPERPORTAL_APP"
CONFIG_DIR="$COMPONENT_DIR/component_config"

update_property "$APP_ID" "isDeployReady"            "$CONFIG_DIR/isDeployReady.md"
update_property "$APP_ID" "shortDescription"         "$CONFIG_DIR/component_short_description.md"
update_property "$APP_ID" "longDescription"          "$CONFIG_DIR/component_long_description.md"
update_property "$APP_ID" "configurationSchema"      "$CONFIG_DIR/configSchema.json"
update_property "$APP_ID" "configurationRowSchema"   "$CONFIG_DIR/configRowSchema.json"
update_property "$APP_ID" "configurationDescription" "$CONFIG_DIR/configuration_description.md"
update_property "$APP_ID" "logger"                   "$CONFIG_DIR/logger"
update_property "$APP_ID" "loggerConfiguration"      "$CONFIG_DIR/loggerConfiguration.json"
update_property "$APP_ID" "licenseUrl"               "$CONFIG_DIR/licenseUrl.md"
update_property "$APP_ID" "documentationUrl"         "$CONFIG_DIR/documentationUrl.md"
update_property "$APP_ID" "sourceCodeUrl"            "$CONFIG_DIR/sourceCodeUrl.md"
update_property "$APP_ID" "uiOptions"                "$CONFIG_DIR/uiOptions.md"

source "$(dirname "$0")/fn_actions_md_update.sh"
update_property "$APP_ID" "actions"                  "$CONFIG_DIR/actions.md"

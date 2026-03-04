#!/bin/bash

# Requires COMPONENT_DIR to be set by the caller (e.g. "extractor" or "writer")
MD_FILE="$COMPONENT_DIR/component_config/actions.md"

# Get all @sync_action declarations from all .py files in the component's src/
SYNC_ACTIONS=$(grep -roh -E "@sync_action\(['\"][^'\"]*['\"]\)" "$COMPONENT_DIR/src/" | sed "s/@sync_action(\(['\"]\)\([^'\"]*\)\(['\"]\))/\2/" | sort | uniq)

# Check if any sync actions were found
if [ -n "$SYNC_ACTIONS" ]; then
    # Iterate over each occurrence of @sync_action('XXX')
    for sync_action in $SYNC_ACTIONS; do
        EXISTING_ACTIONS+=("$sync_action")
    done

    # Convert the array to JSON format
    JSON_ACTIONS=$(printf '"%s",' "${EXISTING_ACTIONS[@]}")
    JSON_ACTIONS="[${JSON_ACTIONS%,}]"

    # Update the content of the actions.md file
    echo "$JSON_ACTIONS" > "$MD_FILE"
else
    echo "No sync actions found. Not creating the file."
fi

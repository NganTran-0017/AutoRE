#!/bin/bash
# make sure to cd into Output before running this script, e.g., `cd Output && ./move_files.sh 22 0513_12PM`

# Check if the number argument is provided
if [ -z "$1" ] || [ -z "$2" ]; then
    echo "Error: Missing matching Iteration number argument."
    echo "Usage: $0 [ITERATION_NUMBER] [TIMESTAMP]"
    exit 1
fi

# Assign the number argument (e.g., 22)
ITERATION="$1"
#TIMESTAMP=$(date +"%m%d_%I%p") # Generates current format like 0513_12PM
TIMESTAMP="$2" # Use the provided timestamp argument

# Define the list of target folders
TARGET_FOLDERS=("AlloyModels" "Feedback" "ReqsDoc")

# Iterate through each folder in the list
for FOLDER in "${TARGET_FOLDERS[@]}"; do
    # Check if the target directory actually exists before running
    if [ -d "$FOLDER" ]; then
        echo "Processing folder: $FOLDER..."
        if [ "$FOLDER" = "AlloyModels" ]; then 
		    EXT="als"
        elif [ "$FOLDER" = "ReqsDoc" ]; then 
		    EXT="txt"
            ITERATION="*" # change this to reflect For ReqsDoc, get the max iteration number and use that instead of the provided one
	    else
		    EXT="txt"
	    fi
        # Execute the workflow for the current folder
        mkdir -p "$FOLDER/$TIMESTAMP" && \
        mv "$FOLDER"/*."$EXT" "$FOLDER/$TIMESTAMP/" && \
        cp "$PWD/$FOLDER/$TIMESTAMP/"*_"${ITERATION}"."$EXT" "$PWD/$FOLDER/" 
        echo "Finished processing $FOLDER. using *.$EXT files from $PWD"
    else
        echo "Skipping $FOLDER (Directory does not exist)."
    fi
done

echo "Moving 2-digit folders to AnalyzerOutput/$TIMESTAMP..."

# Create the target analyzer directory first
mkdir -p "AnalyzerOutput/$TIMESTAMP"

# Execute your specific find command for the current directory (.)
find AnalyzerOutput/ -maxdepth 1 -type d -regex '.*/[0-9][0-9]' -exec mv {} "AnalyzerOutput/$TIMESTAMP/" \;

echo "All folders processed successfully."

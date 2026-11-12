#!/usr/bin/env bash
# Promote the Instruqt track to production: push the current commit's
# instruqt/ to the `temporal` team, where learners use it.
#
# instruqt/ is the testing track, in the `temporal-devrel` team, with that
# team's IDs. The script copies it to a temporary folder, strips every ID and
# the checksum, sets `owner: temporal` and `maintenance: false`, and pushes
# with --force. Instruqt matches the track and its challenges by slug, so they
# keep their production IDs; tabs have no slug, so production gets new tabs.
#
#   scripts/promote-track.sh             # asks for confirmation, then pushes
#   DRY_RUN=1 scripts/promote-track.sh   # shows the production copy, pushes nothing
#
# Needs a clean, committed tree, and an Instruqt login (or INSTRUQT_TOKEN) with
# access to the `temporal` team.
set -euo pipefail
IFS=$'\t\n'

# --- configuration ----------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
SCRIPT_NAME="$(basename "${BASH_SOURCE[0]}")"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TRACK_DIR="$REPO_DIR/instruqt"
TESTING_OWNER="temporal-devrel"
PRODUCTION_OWNER="temporal"
DRY_RUN="${DRY_RUN:-0}"

# --- helpers ----------------------------------------------------------------

die() {
    echo "$SCRIPT_NAME: $*" >&2
    exit 1
}

# Removes every Instruqt ID from one track file: the `id:` line of a track or
# challenge, and the `- id:` line that opens each tab, whose next line then
# opens the tab in its place.
strip_ids() {
    local file="$1"
    awk '
        /^id: [A-Za-z0-9]+[[:space:]]*$/ { next }
        /^- id: [A-Za-z0-9]+[[:space:]]*$/ { opens_tab = 1; next }
        opens_tab { sub(/^  /, "- "); opens_tab = 0 }
        /^checksum:/ { next }
        { print }
    ' "$file" > "$file.stripped"
    mv "$file.stripped" "$file"
}

# Turns the copy in $1 into the production track.
make_production_copy() {
    local copy="$1"
    local file

    for file in $(find "$copy" -name track.yml -o -name assignment.md); do
        strip_ids "$file"
    done

    sed -i.bak \
        -e "s/^owner: $TESTING_OWNER$/owner: $PRODUCTION_OWNER/" \
        -e "s/^maintenance: true$/maintenance: false/" \
        "$copy/track.yml"
    rm -f "$copy/track.yml.bak"

    if ! grep -q "^owner: $PRODUCTION_OWNER$" "$copy/track.yml"; then
        die "track.yml doesn't say owner: $TESTING_OWNER, so there's nothing to promote from."
    fi
    if ! grep -q "^maintenance: false$" "$copy/track.yml"; then
        die "track.yml doesn't say maintenance: true, so it isn't the testing track."
    fi
    if grep -rqE "^(- )?id: " "$copy" --include=track.yml --include=assignment.md; then
        die "some IDs survived stripping; check the track files' format."
    fi
}

# --- promotion --------------------------------------------------------------

main() {
    if [ -n "$(git -C "$REPO_DIR" status --porcelain)" ]; then
        die "commit or stash your changes first: a promotion pushes a commit, not a working tree."
    fi

    local commit
    local work_dir
    local copy
    commit="$(git -C "$REPO_DIR" rev-parse --short HEAD)"
    work_dir="$(mktemp -d)"
    copy="$work_dir/instruqt"
    # Double quotes, so the path is fixed now: the trap runs after main returns,
    # when its local variables are gone.
    trap "rm -rf -- '$work_dir'" EXIT

    cp -R "$TRACK_DIR/." "$copy/"
    make_production_copy "$copy"
    (cd "$copy" && instruqt track validate)

    if [ "$DRY_RUN" = "1" ]; then
        echo
        echo "Dry run: the production copy of $commit differs from instruqt/ like this:"
        diff -r "$TRACK_DIR" "$copy" || true
        echo
        echo "Nothing was pushed."
    else
        echo
        read -r -p "Push commit $commit to the '$PRODUCTION_OWNER' team, where learners use it? [y/N] " answer
        if [ "$answer" = "y" ]; then
            (cd "$copy" && instruqt track push --force)
        else
            echo "Not promoted."
        fi
    fi
}

main "$@"

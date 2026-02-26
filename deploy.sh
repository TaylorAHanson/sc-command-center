#!/bin/bash

# Deploy script for Databricks Apps
# Usage: ./deploy.sh --profile=<profile> --app-name=<app-name>
# Example: ./deploy.sh --profile=supply-dev --app-name=command-center-dev

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ─────────────────────────────────────────────
# Parse arguments
# ─────────────────────────────────────────────
PROFILE=""
APP_NAME=""

for arg in "$@"; do
    case $arg in
        --profile=*)
            PROFILE="${arg#*=}"
            ;;
        --app-name=*)
            APP_NAME="${arg#*=}"
            ;;
        --help|-h)
            echo "Usage: ./deploy.sh --profile=<databricks-profile> --app-name=<app-name>"
            echo ""
            echo "  --profile    Databricks CLI profile (e.g. supply-dev)"
            echo "  --app-name   Databricks App name (e.g. command-center-dev)"
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown argument: $arg${NC}"
            echo "Run ./deploy.sh --help for usage."
            exit 1
            ;;
    esac
done

# Validate required args
if [ -z "$PROFILE" ] || [ -z "$APP_NAME" ]; then
    echo -e "${RED}Error: --profile and --app-name are required.${NC}"
    echo "Run ./deploy.sh --help for usage."
    exit 1
fi

echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  SCCC Deploy to Databricks Apps        ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}Profile:${NC}  $PROFILE"
echo -e "${CYAN}App Name:${NC} $APP_NAME"
echo ""

# ─────────────────────────────────────────────
# Check databricks CLI is available
# ─────────────────────────────────────────────
if ! command -v databricks &> /dev/null; then
    echo -e "${RED}✗ 'databricks' CLI not found. Install it first:${NC}"
    echo "  https://docs.databricks.com/dev-tools/cli/databricks-cli.html"
    exit 1
fi

# ─────────────────────────────────────────────
# Check / prompt for auth
# ─────────────────────────────────────────────
echo -e "${CYAN}Checking authentication for profile '$PROFILE'...${NC}"

# Try a lightweight API call to verify auth works
if databricks --profile "$PROFILE" auth token &> /dev/null; then
    echo -e "${GREEN}✓ Already authenticated with profile '$PROFILE'${NC}"
else
    echo -e "${YELLOW}Not authenticated. Starting login flow...${NC}"
    databricks auth login --profile "$PROFILE"

    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ Authentication failed. Aborting.${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ Logged in successfully${NC}"
fi
echo ""

# ─────────────────────────────────────────────
# Resolve the app's source path
# ─────────────────────────────────────────────
echo -e "${CYAN}Resolving app details for '$APP_NAME'...${NC}"

APP_JSON=$(databricks --profile "$PROFILE" apps get "$APP_NAME" 2>&1)
GET_EXIT=$?

if [ $GET_EXIT -ne 0 ]; then
    echo -e "${RED}✗ Could not find app '$APP_NAME' in profile '$PROFILE'.${NC}"
    echo -e "${YELLOW}Hint: Create the app first via the Databricks UI or CLI, then re-run this script.${NC}"
    echo ""
    echo "App lookup output:"
    echo "$APP_JSON"
    exit 1
fi

echo -e "${GREEN}✓ App found${NC}"
echo ""

# ─────────────────────────────────────────────
# Build frontend
# ─────────────────────────────────────────────
echo -e "${CYAN}Building frontend...${NC}"

if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}node_modules not found. Running npm install...${NC}"
    npm install
    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ npm install failed${NC}"
        exit 1
    fi
fi

npm run build
if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Frontend build failed${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Frontend built${NC}"
echo ""

# ─────────────────────────────────────────────
# Sync source code
# ─────────────────────────────────────────────
echo -e "${CYAN}Syncing source code to Databricks workspace...${NC}"

# databricks sync uses the .databricks/project.json or --source-dir / --dest-dir flags.
# We sync once (not watch mode) using --watch=false and pick up the target from the
# existing .databricks config if present, or derive it from the app name.
SYNC_TARGET="/Workspace/Apps/$APP_NAME"

databricks sync \
    --profile "$PROFILE" \
    --source-dir "." \
    --dest-dir "$SYNC_TARGET" \
    --full

SYNC_EXIT=$?

if [ $SYNC_EXIT -ne 0 ]; then
    echo -e "${RED}✗ Sync failed (exit code $SYNC_EXIT)${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Code synced to $SYNC_TARGET${NC}"
echo ""

# ─────────────────────────────────────────────
# Deploy the app
# ─────────────────────────────────────────────
echo -e "${CYAN}Deploying app '$APP_NAME'...${NC}"

databricks apps deploy "$APP_NAME" \
    --profile "$PROFILE" \
    --source-code-path "$SYNC_TARGET"

DEPLOY_EXIT=$?

if [ $DEPLOY_EXIT -ne 0 ]; then
    echo -e "${RED}✗ App deploy failed (exit code $DEPLOY_EXIT)${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  ✓ Deploy complete!                    ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}App:${NC}     $APP_NAME"
echo -e "${CYAN}Profile:${NC} $PROFILE"
echo -e "${CYAN}Path:${NC}    $SYNC_TARGET"

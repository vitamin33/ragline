#!/usr/bin/env python3
"""
Generate OpenAPI specification from FastAPI application
"""

import json
import sys
from pathlib import Path

import yaml

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def generate_openapi_spec():
    """Generate OpenAPI specification from FastAPI app"""
    print("🔧 Generating OpenAPI specification from FastAPI application...")

    try:
        # Import the FastAPI app
        from services.api.main import app

        # Get the OpenAPI JSON schema
        openapi_json = app.openapi()

        # Enhance the specification with additional metadata
        openapi_json.update(
            {
                "info": {
                    "title": "RAGline Core API",
                    "description": "Streaming-first, multi-tenant Python backend with idempotency, outbox pattern, and Redis Streams",
                    "version": "1.0.0",
                    "contact": {
                        "name": "RAGline Development Team",
                        "url": "https://github.com/vitamin33/ragline",
                    },
                    "license": {
                        "name": "MIT",
                        "url": "https://opensource.org/licenses/MIT",
                    },
                },
                "servers": [
                    {
                        "url": "http://localhost:8000",
                        "description": "Development server",
                    },
                    {
                        "url": "https://api.ragline.com",
                        "description": "Production server",
                    },
                ],
            }
        )

        # Add security schemes
        if "components" not in openapi_json:
            openapi_json["components"] = {}

        openapi_json["components"]["securitySchemes"] = {
            "HTTPBearer": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "JWT token authentication with tenant_id and roles in claims",
            }
        }

        # Add global security requirement
        openapi_json["security"] = [{"HTTPBearer": []}]

        # Write to contracts/openapi.yaml
        contracts_dir = project_root / "contracts"
        openapi_file = contracts_dir / "openapi.yaml"

        # Ensure contracts directory exists
        contracts_dir.mkdir(exist_ok=True)

        # Write YAML file
        with open(openapi_file, "w") as f:
            yaml.dump(openapi_json, f, default_flow_style=False, sort_keys=False, indent=2)

        print(f"✅ OpenAPI specification generated: {openapi_file}")
        print(f"📊 Endpoints documented: {len(openapi_json.get('paths', {}))}")
        print(f"📋 Components defined: {len(openapi_json.get('components', {}).get('schemas', {}))}")

        # Also save JSON version for debugging
        json_file = contracts_dir / "openapi.json"
        with open(json_file, "w") as f:
            json.dump(openapi_json, f, indent=2)
        print(f"🔍 JSON version saved: {json_file}")

        return True

    except Exception as e:
        print(f"❌ Error generating OpenAPI spec: {e}")
        return False


def validate_openapi_spec():
    """Validate the generated OpenAPI specification"""
    print("\n🔍 Validating generated OpenAPI specification...")

    try:
        contracts_dir = project_root / "contracts"
        openapi_file = contracts_dir / "openapi.yaml"

        if not openapi_file.exists():
            print("❌ OpenAPI file not found")
            return False

        # Load and validate YAML
        with open(openapi_file, "r") as f:
            openapi_spec = yaml.safe_load(f)

        # Basic validation
        required_fields = ["openapi", "info", "paths"]
        for field in required_fields:
            if field not in openapi_spec:
                print(f"❌ Missing required field: {field}")
                return False

        print("✅ OpenAPI specification is valid")
        print(f"   OpenAPI Version: {openapi_spec.get('openapi')}")
        print(f"   API Title: {openapi_spec['info'].get('title')}")
        print(f"   API Version: {openapi_spec['info'].get('version')}")
        print(f"   Endpoints: {len(openapi_spec.get('paths', {}))}")

        return True

    except Exception as e:
        print(f"❌ Validation error: {e}")
        return False


def main():
    """Main function"""
    print("🚀 RAGline OpenAPI Generator")
    print("=" * 60)

    # Generate specification
    if not generate_openapi_spec():
        print("❌ Failed to generate OpenAPI specification")
        return 1

    # Validate specification
    if not validate_openapi_spec():
        print("❌ Generated specification is invalid")
        return 1

    print("\n🎉 OpenAPI specification successfully generated and validated!")
    print("📁 Location: contracts/openapi.yaml")
    print("🔗 View docs: http://localhost:8000/docs (when server is running)")

    return 0


if __name__ == "__main__":
    sys.exit(main())

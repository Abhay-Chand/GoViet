import sys
import os

print("=" * 60)
print("Pinecone Installation Check")
print("=" * 60)

# Check Python version
print(f"\n✓ Python: {sys.version}")
print(f"✓ Virtual env: {sys.prefix}")

# Check for pinecone files
venv_path = sys.prefix
pinecone_dirs = []
site_packages = os.path.join(venv_path, "Lib", "site-packages")

if os.path.exists(site_packages):
    for item in os.listdir(site_packages):
        if "pinecone" in item.lower():
            pinecone_dirs.append(item)

print(f"\n📁 Pinecone-related directories found: {len(pinecone_dirs)}")
for d in pinecone_dirs:
    print(f"   - {d}")

# Try import
print("\n🔍 Attempting import...")
try:
    import pinecone
    print(f"✅ SUCCESS! Version: {pinecone.__version__}")
    print(f"✅ Location: {pinecone.__file__}")
except Exception as e:
    print(f"❌ FAILED: {e}")

print("=" * 60)
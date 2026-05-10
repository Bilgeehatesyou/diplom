# ════════════════════════════════════════════════════════════
#  Common Voice 16.0 Mongolian — дата цуглуулах скрипт
#  Ажиллуулах: bash scripts/download_commonvoice.sh
# ════════════════════════════════════════════════════════════
set -e

DATASET_DIR="./data/commonvoice25/mn"
LANG="mn"
VERSION="cv-corpus-25.0-2026-03-09"
ARCHIVE="${VERSION}-${LANG}.tgz"
TARBALL_URL="https://commonvoice.mozilla.org/datasets/${ARCHIVE}"

mkdir -p "$DATASET_DIR"

echo "📥 Common Voice 16.0 Mongolian дата татаж байна..."
echo "   URL: $TARBALL_URL"
echo "   Хэмжээ: ~2.5GB"
echo "   Энэ нь цаг хүртэл удаан байж болно..."

if [ -f "$DATASET_DIR/$ARCHIVE" ]; then
    echo "✅ Архив аль хэдийн татагдсан: $ARCHIVE"
else
    wget -c "$TARBALL_URL" -O "$DATASET_DIR/$ARCHIVE" || \
    curl -L "$TARBALL_URL" -o "$DATASET_DIR/$ARCHIVE"
fi

echo "📦 Архивыг задлах..."
tar -xzf "$DATASET_DIR/$ARCHIVE" -C "$DATASET_DIR"
mv "$DATASET_DIR/$VERSION/$LANG"/* "$DATASET_DIR/" 2>/dev/null || true
rm -rf "$DATASET_DIR/$VERSION"

echo "✅ Common Voice 16.0 Mongolian бэлэн!"
echo ""
echo "   Цуглуулсан файлнууд:"
ls -lh "$DATASET_DIR/"*.tsv 2>/dev/null || echo "   (tsv файлнууд олдсонгүй)"
echo ""
echo "   Дараах тушаал biar xxeed:"
echo "   python scripts/prepare_commonvoice.py"

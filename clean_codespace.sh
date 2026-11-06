#!/usr/bin/env bash
# ==============================================================================
# Script: clean_codespace.sh
# Purpose: Free up disk space in GitHub Codespaces for News Video Generator
# ==============================================================================

set -e

echo "=================================================="
echo "🧹 Начало очистки диска в GitHub Codespaces"
echo "=================================================="
echo "📊 Доступное место ДО очистки:"
df -h /

echo ""
echo "1. 🗑️ Удаление временных файлов генератора (temp/*)..."
if [ -d "temp" ]; then
    rm -rf temp/*
    echo "   -> Папка temp/ очищена."
fi
rm -rf /tmp/* 2>/dev/null || true

echo "2. 🐳 Очистка кэша Docker (образы, слои, кэш сборки)..."
if command -v docker &> /dev/null; then
    docker system prune -af --volumes || true
    echo "   -> Кэш Docker очищен."
else
    echo "   -> Docker не установлен или недоступен, пропуск."
fi

echo "3. 📦 Очистка кэша pip и apt..."
pip cache purge 2>/dev/null || true
rm -rf ~/.cache/pip 2>/dev/null || true
rm -rf ~/.cache/thumbnails 2>/dev/null || true
if command -v apt-get &> /dev/null; then
    sudo apt-get clean 2>/dev/null || true
    sudo rm -rf /var/lib/apt/lists/* 2>/dev/null || true
fi
echo "   -> Системные кэши очищены."

echo "4. 📜 Сжатие системных логов journald..."
if command -v journalctl &> /dev/null; then
    sudo journalctl --vacuum-size=50M 2>/dev/null || true
fi

echo "5. 📹 Удаление старых промежуточных файлов в output/..."
# Удаляем промежуточные папки kb_clips, kb_trans, kb_chunks если они где-то остались
find output/ -type d \( -name "kb_clips" -o -name "kb_trans" -o -name "kb_chunks" -o -name "transitions" \) -exec rm -rf {} + 2>/dev/null || true

echo ""
echo "=================================================="
echo "✅ Очистка завершена!"
echo "📊 Доступное место ПОСЛЕ очистки:"
df -h /
echo "=================================================="
echo "Теперь вы можете вернуться в интерфейс и нажать 'Продолжить с сохранённого места'!"

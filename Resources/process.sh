#!/bin/zsh
# launchd 在 queue 非空时启动本脚本：逐个把 zip 移进 archive，再交给 wx2miaoyan.py 写进 Obsidian。
# 先移走再转换：queue 里留着文件，launchd 会一直重启本脚本。
set -u

data="$HOME/Library/Application Support/WxToOb"
queue="$data/queue"
archive="$data/archive"
log="$data/process.log"
converter=/Users/apple/xuxu/wx2miaoyan/wx2miaoyan.py
py=/opt/homebrew/bin/python3

mkdir -p "$archive"
exec >> "$log" 2>&1

for zip in "$queue"/*.zip(N); do
  dst="$archive/${zip:t}"
  echo "[$(date '+%F %T')] 处理 ${zip:t}"
  if ! mv "$zip" "$dst"; then
    echo "  移动到 archive 失败，退出等 launchd 重试"
    exit 1
  fi
  "$py" "$converter" "$dst"
  echo "  exit: $?"
done

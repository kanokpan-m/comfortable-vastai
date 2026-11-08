# Install the Comfortable ComfyUI extension (sidebar tab + smart fixer) by linking
# comfyui_ext into ComfyUI's custom_nodes. Sourced by lib/main.sh and lib/update.sh.
# Takes effect when ComfyUI (re)starts; on first boot ComfyUI starts after provisioning.
CUSTOM_NODES=/workspace/ComfyUI/custom_nodes
EXT_NAME=ComfyUI-Comfortable
if [[ -d "$CUSTOM_NODES" && "${COMFORTABLE_COMFY_EXTENSION:-1}" != 0 ]]; then
  ln -sfn "$COMFORTABLE_DIR/comfyui_ext" "$CUSTOM_NODES/$EXT_NAME"
  log "ComfyUI extension linked: $CUSTOM_NODES/$EXT_NAME -> $COMFORTABLE_DIR/comfyui_ext"
elif [[ "${COMFORTABLE_COMFY_EXTENSION:-1}" == 0 ]]; then
  rm -f "$CUSTOM_NODES/$EXT_NAME"
fi

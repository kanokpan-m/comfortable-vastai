// Icons for catalog packs by kind (placeholders, circles, cards).
import { Box, Cpu, Layers, Film, Spline, Wand2, Wrench, Sparkles, Package, Axis3d, Music } from '@lucide/vue'

const KIND = { checkpoint: Box, base: Cpu, lora: Layers, video: Film, controlnet: Spline, upscaler: Wand2, tool: Wrench, embedding: Sparkles }
// Models that make something other than pictures or video get their own icon.
const MADE = { '3d': Axis3d, audio: Music }
export const kindIcon = (pack) =>
  (pack?.kind !== 'video' && (pack?.categories || []).map((c) => MADE[c]).find(Boolean)) || KIND[pack?.kind] || Package

<template>
  <input v-if="flag.type === 'boolean'" type="checkbox" :checked="!!flag.value" @change="emitVal(($event.target as HTMLInputElement).checked)" class="h-5 w-5" />
  <input v-else-if="flag.type === 'number'" type="number" :value="flag.value as number" @input="emitVal(Number(($event.target as HTMLInputElement).value))" class="border rounded px-2 py-1 w-28" />
  <input v-else type="text" :value="String(flag.value ?? '')" @input="emitVal(($event.target as HTMLInputElement).value)" class="border rounded px-2 py-1 w-64" />
</template>
<script setup lang="ts">
import type { Flag } from '../stores/flags'
defineProps<{ flag: Flag }>()
const emit = defineEmits<{ (e: 'save', v: unknown): void }>()
function emitVal(v: unknown) { emit('save', v) }
</script>

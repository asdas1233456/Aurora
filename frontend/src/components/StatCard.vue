<template>
  <div class="stat-card">
    <p class="stat-label">{{ label }}</p>
    <h3 class="stat-value">{{ value }}</h3>
    <p v-if="hint" class="stat-hint">{{ hint }}</p>
  </div>
</template>

<script setup>
defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], required: true },
  hint: { type: String, default: "" },
});
</script>

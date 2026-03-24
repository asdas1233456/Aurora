<template>
  <section class="panel-card">
    <div class="section-header">
      <h3>{{ title }}</h3>
      <span v-if="tag" class="tag">{{ tag }}</span>
    </div>
    <slot />
  </section>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  tag: { type: String, default: "" },
});
</script>


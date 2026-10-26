/* The condition builder of a notification rule's admin form: rows of {field, op, value} over the chosen event
 * type's fields, all or any of them, written into the condition's JSON (the textarea, also editable by hand). A
 * nested condition, or JSON that doesn't parse, is left to the textarea. The server validates it on save. */
(function () {
  "use strict";

  function element(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (key === "text") node.textContent = value;
      else node.setAttribute(key, value);
    });
    (children || []).forEach((child) => node.append(child));
    return node;
  }

  function select(options, value, className) {
    const node = element("select", { class: className });
    options.forEach(([code, label]) => {
      const option = element("option", { value: code, text: label });
      if (String(code) === String(value)) option.selected = true;
      node.append(option);
    });
    return node;
  }

  function flat(condition) {
    if (!condition || Object.keys(condition).length === 0) return { mode: "all", items: [] };
    if (condition.field) return { mode: "all", items: [condition] };
    const mode = Array.isArray(condition.all) ? "all" : Array.isArray(condition.any) ? "any" : null;
    if (!mode || condition[mode].some((item) => !item || !item.field)) return null;
    return { mode, items: condition[mode].map((item) => Object.assign({}, item)) };
  }

  function init(root) {
    const schemas = JSON.parse(root.dataset.schemas || "{}");
    const textarea = root.querySelector("textarea");
    const builder = root.querySelector(".nr-builder");
    const eventSelect = document.getElementById(root.dataset.eventField);
    let state = null;

    function write() {
      const items = state.items.map((item) => {
        const clean = { field: item.field, op: item.op };
        if (item.value !== undefined && item.value !== "") clean.value = item.value;
        return clean;
      });
      textarea.value = items.length ? JSON.stringify({ [state.mode]: items }, null, 2) : "{}";
    }

    function row(schema, item, index) {
      const fields = schema.fields.map((f) => [f.name, f.label === f.name ? f.name : `${f.label} (${f.name})`]);
      const field = schema.fields.find((f) => f.name === item.field) || schema.fields[0];
      const operators = Object.entries(schema.operators[field.type] || {});
      if (!operators.some(([op]) => op === item.op)) item.op = operators[0][0];
      const fieldSelect = select(fields, field.name, "nr-field");
      const opSelect = select(operators, item.op, "nr-op");
      const unary = schema.unary.includes(item.op);
      const value = element("input", {
        class: "nr-value", type: "text", value: item.value === undefined ? "" : String(item.value),
        placeholder: schema.lists.includes(item.op) ? "a, b, c" : field.type,
      });
      if (field.choices.length) {
        const list = `nr-choices-${field.name}`;
        value.setAttribute("list", list);
        root.append(element("datalist", { id: list }, field.choices.map((c) => element("option", { value: c }))));
      }
      value.hidden = unary;
      const remove = element("button", { type: "button", class: "nr-remove", text: "×", title: "Remove" });
      fieldSelect.addEventListener("change", () => { item.field = fieldSelect.value; item.value = ""; write(); render(); });
      opSelect.addEventListener("change", () => { item.op = opSelect.value; write(); render(); });
      value.addEventListener("input", () => { item.value = value.value; write(); });
      remove.addEventListener("click", () => { state.items.splice(index, 1); write(); render(); });
      item.field = field.name;
      return element("div", { class: "nr-row" }, [fieldSelect, opSelect, value, remove]);
    }

    function render() {
      builder.textContent = "";
      const schema = schemas[eventSelect ? eventSelect.value : ""];
      let parsed;
      try { parsed = JSON.parse(textarea.value || "{}"); } catch (error) { parsed = undefined; }
      state = parsed === undefined ? null : flat(parsed);
      if (!schema) {
        builder.append(element("p", { class: "help", text: "Choose the event to build its condition." }));
        return;
      }
      if (!state) {
        builder.append(element("p", { class: "help", text: "A nested condition, or JSON that doesn't parse: edit it as JSON." }));
        return;
      }
      if (!schema.fields.length) {
        builder.append(element("p", { class: "help", text: "This event has no fields: its rules apply to every event." }));
        return;
      }
      const mode = select([["all", "All of these hold"], ["any", "Any of these holds"]], state.mode, "nr-mode");
      mode.addEventListener("change", () => { state.mode = mode.value; write(); });
      builder.append(mode);
      state.items.forEach((item, index) => builder.append(row(schema, item, index)));
      if (!state.items.length) builder.append(element("p", { class: "help", text: "No test: every event." }));
      const add = element("button", { type: "button", class: "nr-add", text: "+ Add a test" });
      add.addEventListener("click", () => { state.items.push({ field: schema.fields[0].name, op: "" }); write(); render(); });
      builder.append(add);
    }

    textarea.addEventListener("change", render);
    if (eventSelect) eventSelect.addEventListener("change", render);
    render();
  }

  document.addEventListener("DOMContentLoaded", () => document.querySelectorAll(".nr-condition").forEach(init));
})();

/**
 * Editor compartido de condiciones "campo / operador / valor" encadenadas con Y/O.
 *
 * Usado por: Reglas de automatización (regla_form.html), el panel de
 * disparadores (mismo template), el nodo "Condición" del Flujo visual
 * (flujo_canvas.html) y el nodo "Condición" del bot de WhatsApp
 * (bot_builder.html).
 *
 * Requiere un "registro de campos" (array de
 * {value, label, type, options:[{v,l},...]}) inyectado por la vista
 * (ver `apps.automations.views._condicion_campos`).
 */

function escCondHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** Opciones <option> para el <select> de "campo". */
function condicionCampoOptions(registry, currentValue, includeAny) {
  let html = '';
  let found = false;
  if (includeAny) {
    html += `<option value="" ${!currentValue ? 'selected' : ''}>Cualquier campo</option>`;
    if (!currentValue) found = true;
  }
  (registry || []).forEach(f => {
    const isSel = f.value === currentValue;
    if (isSel) found = true;
    html += `<option value="${escCondHtml(f.value)}" ${isSel ? 'selected' : ''}>${escCondHtml(f.label)}</option>`;
  });
  if (currentValue && !found) {
    html += `<option value="${escCondHtml(currentValue)}" selected>${escCondHtml(currentValue)} (no disponible)</option>`;
  }
  return html;
}

/**
 * Control de "valor" dinámico según el tipo del campo seleccionado:
 * select con opciones reales (etapas, prioridad, origen, listas personalizadas, etc.),
 * input numérico, input de fecha, o input de texto libre por defecto.
 */
function condicionValorControl(registry, campoValue, currentValue, opts = {}) {
  const { name = null, size = 'sm', className = 'cond-valor' } = opts;
  const sizeSuffix = size ? `-${size}` : '';
  const nameAttr = name ? ` name="${escCondHtml(name)}"` : '';
  const def = (registry || []).find(f => f.value === campoValue);
  const cur = currentValue == null ? '' : currentValue;

  if (def && def.type === 'select') {
    const opts_ = (def.options || []).map(o =>
      `<option value="${escCondHtml(o.v)}" ${String(o.v) === String(cur) ? 'selected' : ''}>${escCondHtml(o.l)}</option>`
    ).join('');
    return `<select class="form-select form-select${sizeSuffix} ${className}"${nameAttr}>` +
           `<option value="">— Elegir —</option>${opts_}</select>`;
  }
  if (def && def.type === 'number') {
    return `<input type="number" class="form-control form-control${sizeSuffix} ${className}"${nameAttr} value="${escCondHtml(cur)}">`;
  }
  if (def && def.type === 'date') {
    return `<input type="date" class="form-control form-control${sizeSuffix} ${className}"${nameAttr} value="${escCondHtml(cur)}">`;
  }
  return `<input type="text" class="form-control form-control${sizeSuffix} ${className}"${nameAttr} value="${escCondHtml(cur)}" placeholder="valor...">`;
}

/**
 * Renderiza una lista editable de condiciones {campo, operador, valor, conector}
 * dentro de `container`, con botones de eliminar y badges Y/O alternables.
 * Llama a `onChange(condiciones)` después de cada edición.
 *
 * opts:
 *  - emptyMsg: texto cuando la lista está vacía
 *  - includeAnyField: si true, agrega "Cualquier campo" (value='') al selector de campo
 */
function renderCondicionesEditor(container, conditions, registry, operadores, onChange, opts = {}) {
  const emptyMsg = opts.emptyMsg || 'Sin condiciones.';
  container.innerHTML = '';
  if (!conditions.length) {
    const p = document.createElement('p');
    p.className = 'text-muted small mb-2 cond-empty-msg';
    p.textContent = emptyMsg;
    container.appendChild(p);
  }

  function syncFromDOM() {
    return Array.from(container.querySelectorAll('.cond-block')).map(block => ({
      campo: block.querySelector('.cond-campo').value,
      operador: block.querySelector('.cond-operador').value,
      valor: block.querySelector('.cond-valor').value,
      conector: block.dataset.conector || 'Y',
    }));
  }

  conditions.forEach((cond, idx) => {
    if (idx > 0) {
      const conector = conditions[idx - 1].conector || 'Y';
      const join = document.createElement('div');
      join.className = 'mb-2';
      join.innerHTML = `<span class="badge cond-join-badge ${conector === 'Y' ? 'bg-warning-subtle text-warning-emphasis' : 'bg-info-subtle text-info-emphasis'}" data-idx="${idx - 1}" style="cursor:pointer" title="Click para alternar Y / O">${conector}</span>`;
      container.appendChild(join);
    }

    const block = document.createElement('div');
    block.className = 'cond-block border rounded-3 p-2 mb-2 d-flex gap-2 align-items-center flex-wrap';
    block.dataset.conector = cond.conector || 'Y';

    const campoSel = document.createElement('select');
    campoSel.className = 'form-select form-select-sm cond-campo';
    campoSel.style.maxWidth = '200px';
    campoSel.innerHTML = condicionCampoOptions(registry, cond.campo, !!opts.includeAnyField);

    const opSel = document.createElement('select');
    opSel.className = 'form-select form-select-sm cond-operador';
    opSel.style.maxWidth = '170px';
    (operadores || []).forEach(o => {
      const opt = document.createElement('option');
      opt.value = o.value;
      opt.textContent = o.label;
      if (o.value === cond.operador) opt.selected = true;
      opSel.appendChild(opt);
    });

    const valWrap = document.createElement('span');
    valWrap.className = 'cond-valor-wrap';
    valWrap.style.maxWidth = '200px';
    valWrap.innerHTML = condicionValorControl(registry, cond.campo, cond.valor || '');

    function syncValVisibility() {
      valWrap.style.display = (opSel.value === 'empty' || opSel.value === 'not_empty') ? 'none' : '';
    }
    syncValVisibility();

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'btn btn-sm btn-outline-danger';
    removeBtn.title = 'Quitar condición';
    removeBtn.innerHTML = '<i class="bi bi-x-lg"></i>';

    block.append(campoSel, opSel, valWrap, removeBtn);
    container.appendChild(block);

    campoSel.addEventListener('change', () => {
      valWrap.innerHTML = condicionValorControl(registry, campoSel.value, '');
      syncValVisibility();
      onChange(syncFromDOM());
    });
    opSel.addEventListener('change', () => {
      syncValVisibility();
      onChange(syncFromDOM());
    });
    valWrap.addEventListener('change', () => onChange(syncFromDOM()));
    valWrap.addEventListener('input', () => onChange(syncFromDOM()));
    removeBtn.addEventListener('click', () => {
      const next = syncFromDOM();
      next.splice(idx, 1);
      renderCondicionesEditor(container, next, registry, operadores, onChange, opts);
      onChange(next);
    });
  });

  container.querySelectorAll('.cond-join-badge').forEach(badge => {
    badge.addEventListener('click', () => {
      const next = syncFromDOM();
      const i = parseInt(badge.dataset.idx, 10);
      next[i].conector = next[i].conector === 'Y' ? 'O' : 'Y';
      renderCondicionesEditor(container, next, registry, operadores, onChange, opts);
      onChange(next);
    });
  });
}

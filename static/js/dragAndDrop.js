import { clusterize } from './render.js'

export const handleDragStart = event => {
    const target = event.target.closest('.changeset-item')
    event.dataTransfer.setData('text/plain', target.dataset.id)
    target.classList.add('dragging')
    document.getElementsByTagName('body')[0].classList.add('dragging')
}

export const handleDragEnd = event => {
    const target = event.target.closest('.changeset-item')
    target.classList.remove('dragging')
    document.getElementsByTagName('body')[0].classList.remove('dragging')
}

export const handleDragOver = event => {
    event.preventDefault()
}

const dragEnterCounters = new Map()

export const handleDragEnter = event => {
    const target = event.target.closest('.changeset-item') || event.target.closest('.changeset-list')
    if (!target) return

    if (target.classList.contains('changeset-item')) {
        const count = (dragEnterCounters.get(target) || 0) + 1
        dragEnterCounters.set(target, count)
    }

    target.classList.add('dragging-effects')
}

export const handleDragLeave = event => {
    const target = event.target.closest('.changeset-item') || event.target.closest('.changeset-list')
    if (!target) return

    if (target.classList.contains('changeset-item')) {
        const count = (dragEnterCounters.get(target) || 1) - 1
        dragEnterCounters.set(target, count)
        if (count > 0) return
    }

    target.classList.remove('dragging-effects')
}

export const handleDrop = event => {
    event.preventDefault()

    const draggedItemId = parseInt(event.dataTransfer.getData('text/plain'))
    const draggedItem = document.querySelector(`.changeset-item[data-id="${draggedItemId}"]`)
    if (!draggedItem) {
        console.error(`Cannot find changeset item with id ${draggedItemId}`)
        return
    }

    const draggedCategory = draggedItem.closest('.category').id
    const draggedClusterize = clusterize[draggedCategory]
    const draggedItemIndex = draggedClusterize.ids.indexOf(draggedItemId)
    if (draggedItemIndex < 0) {
        console.error(`Cannot find clusterize index with id ${draggedItemId}`)
        return
    }

    document.querySelectorAll('.dragging-effects').forEach(e => e.classList.remove('dragging-effects'))
    dragEnterCounters.clear()

    const targetItem = event.target.closest('.changeset-item')
    const targetCategory = event.target.closest('.category').id
    const targetClusterize = clusterize[targetCategory]

    // do nothing if dropped on the same item
    if (targetItem && draggedItem === targetItem) return

    const removedId = draggedClusterize.ids.splice(draggedItemIndex, 1)[0]
    const removedRow = draggedClusterize.rows.splice(draggedItemIndex, 1)[0]

    if (targetItem) {
        const targetItemId = targetItem.dataset.id
        const targetItemIndex = targetClusterize.ids.indexOf(targetItemId)

        // insert before target item
        targetClusterize.ids.splice(targetItemIndex, 0, removedId)
        targetClusterize.rows.splice(targetItemIndex, 0, removedRow)
    }
    else {
        // insert at the end
        targetClusterize.ids.push(removedId)
        targetClusterize.rows.push(removedRow)
    }

    if (draggedCategory === targetCategory) {
        targetClusterize.customUpdate(targetClusterize.ids, targetClusterize.rows)
    }
    else {
        draggedClusterize.customUpdate(draggedClusterize.ids, draggedClusterize.rows)
        targetClusterize.customUpdate(targetClusterize.ids, targetClusterize.rows)
    }

    document.querySelectorAll('.dragging-effects').forEach(element => {
        element.classList.remove('dragging-effects')
    })
}

export const initializeDragAndDrop = () => {
    document.querySelectorAll('.changeset-item').forEach(element => {
        if (element.dataset.dragAndDropInitialized) return
        element.addEventListener('dragstart', handleDragStart)
        element.addEventListener('dragend', handleDragEnd)
        element.dataset.dragAndDropInitialized = true
    })

    document.querySelectorAll('.changeset-list').forEach(element => {
        if (element.dataset.dragAndDropInitialized) return
        element.addEventListener('dragenter', handleDragEnter)
        element.addEventListener('dragleave', handleDragLeave)
        element.addEventListener('dragover', handleDragOver)
        element.addEventListener('drop', handleDrop)
        element.dataset.dragAndDropInitialized = true
    })
}

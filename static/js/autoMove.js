import { clusterize } from './render.js'

export const handleFormClick = event => {
    const btn = event.target
    const checks = []

    for (const input of document.querySelectorAll('[data-auto-move]')) {
        if (!input.checked) continue
        const kind = input.dataset.autoMove

        if (kind === 'blocked') {
            checks.push(cs => cs._blocked)
        } else if (kind === 'deleted') {
            checks.push(cs => cs._deleted)
        } else {
            console.error('Unknown auto-move checkbox', input)
            return
        }
    }

    // do nothing if no checks
    if (checks.length === 0) return

    const currentClusterize = clusterize[btn.dataset.autoMoveFrom]
    const targetClusterize = clusterize[btn.dataset.autoMoveTo]

    const moveIndices = new Set()
    const moveIds = []
    const moveRows = []

    currentClusterize.ids.forEach((id, index) => {
        if (checks.some(check => check(window.changesets[id]))) {
            moveIndices.add(index)
            moveIds.push(id)
            moveRows.push(currentClusterize.rows[index])
        }
    })

    currentClusterize.ids = currentClusterize.ids.filter((_, index) => !moveIndices.has(index))
    currentClusterize.rows = currentClusterize.rows.filter((_, index) => !moveIndices.has(index))

    targetClusterize.ids.push(...moveIds)
    targetClusterize.rows.push(...moveRows)

    currentClusterize.customUpdate(currentClusterize.ids, currentClusterize.rows)
    targetClusterize.customUpdate(targetClusterize.ids, targetClusterize.rows)
}

export const handleChangesetClick = event => {
    const btn = event.target
    const changesetItem = btn.closest('.changeset-item')
    const changesetId = changesetItem.dataset.id
    const changeset = window.changesets[changesetId]

    let getValueFn = undefined
    let toCategory = undefined

    if (btn.dataset.autoMoveUserTo) {
        getValueFn = cs => cs['@user']
        toCategory = btn.dataset.autoMoveUserTo
    } else if (btn.dataset.autoMoveCommentTo) {
        getValueFn = cs => cs.tags.comment
        toCategory = btn.dataset.autoMoveCommentTo
    } else {
        console.error('Unknown auto-move button', btn)
        return
    }

    const value = getValueFn(changeset)
    const currentClusterize = clusterize[changesetItem.closest('.category').id]
    const targetClusterize = clusterize[toCategory]

    const moveIndices = new Set()
    const moveIds = []
    const moveRows = []

    currentClusterize.ids.forEach((id, index) => {
        if (getValueFn(window.changesets[id]) === value) {
            moveIndices.add(index)
            moveIds.push(id)
            moveRows.push(currentClusterize.rows[index])
        }
    })

    currentClusterize.ids = currentClusterize.ids.filter((_, index) => !moveIndices.has(index))
    currentClusterize.rows = currentClusterize.rows.filter((_, index) => !moveIndices.has(index))

    targetClusterize.ids.push(...moveIds)
    targetClusterize.rows.push(...moveRows)

    currentClusterize.customUpdate(currentClusterize.ids, currentClusterize.rows)
    targetClusterize.customUpdate(targetClusterize.ids, targetClusterize.rows)
}

export const initializeAutoMove = () => {
    ['[data-auto-move-user-to]', '[data-auto-move-comment-to]'].forEach(selector => {
        document.querySelectorAll(selector).forEach(element => {
            if (element.dataset.autoMoveInitialized) return
            element.addEventListener('click', handleChangesetClick)
            element.dataset.autoMoveInitialized = true
        })
    })

    document.querySelectorAll('[data-auto-move-to]').forEach(element => {
        if (element.dataset.autoMoveInitialized) return
        element.addEventListener('click', handleFormClick)
        element.dataset.autoMoveInitialized = true
    })
}

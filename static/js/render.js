import { initializeAutoMove } from './autoMove.js'
import { initializeDragAndDrop } from './dragAndDrop.js'

const updateCounters = () => {
    try {
        ['legitimate', 'uncategorized', 'malicious'].forEach(category => {
            const count = clusterize[category].getRowsAmount()
            document.getElementById(category).querySelector('.counter').textContent = count
        })
    }
    catch (e) {
        // pass
    }
}

const initClusterize = category => {
    const container = document.getElementById(category).querySelector('.changeset-list')
    const clusterize = new Clusterize({
        scrollElem: container,
        contentElem: container.querySelector('.clusterize-content'),
        show_no_data_row: false,
        callbacks: {
            clusterChanged: () => {
                initializeDragAndDrop()
                initializeAutoMove()
            }
        }
    })

    clusterize.ids = []
    clusterize.rows = []

    clusterize.customUpdate = (ids, rows) => {
        clusterize.ids = ids
        clusterize.rows = rows
        clusterize.update(rows)
        updateCounters()
    }

    return clusterize
}

export const clusterize = {}

const escapeHTML = str => {
    const div = document.createElement('div')
    div.textContent = str
    return div.innerHTML
}

export const renderChangesets = changesets => {
    ['legitimate', 'uncategorized', 'malicious'].forEach(category => {
        clusterize[category] = initClusterize(category)
    })

    const ids = Object.keys(changesets)
    const rows = Object.values(changesets).map(cs => {
        const escapedUser = escapeHTML(cs['@user'])
        const escapedComment = escapeHTML(cs.tags.comment || '(no comment)')
        let userPrefix = ''

        if (cs._deleted)
            userPrefix += '<span title="Deleted account">☠️</span>'

        if (cs._blocked)
            userPrefix += '<span title="Blocked user">🚫</span>'

        return `
        <div class="changeset-item py-1" data-id="${cs['@id']}" draggable="true">
            <div class="card">
                <div class="card-body">
                    <div class="row g-1">
                        <div class="col-10">
                            <h6 class="card-title header mb-1">
                                <a href="https://www.openstreetmap.org/changeset/${cs['@id']}" target="_blank">#${cs['@id']}</a>
                                by
                                ${userPrefix}
                                <a href="https://www.openstreetmap.org/user/${encodeURIComponent(cs['@user'])}" target="_blank">${escapedUser}</a>
                            </h6>
                            <p class="comment mb-0" title="${escapedComment}">${escapedComment}</p>
                        </div>
                        <div class="col-2 text-end">
                            <div class="micro" title="Auto-move ${escapedUser} user">
                                <span class="font-monospace">u</span>
                                <button class="btn btn-light hide-legitimate" data-auto-move-user-to="legitimate">🟢</button>
                                <button class="btn btn-light hide-uncategorized" data-auto-move-user-to="uncategorized">⚪</button>
                                <button class="btn btn-light hide-malicious" data-auto-move-user-to="malicious">🔴</button>
                            </div>
                            <div class="micro" title="Auto-move '${escapedComment}' comment">
                                <span class="font-monospace">c</span>
                                <button class="btn btn-light hide-legitimate" data-auto-move-comment-to="legitimate">🟢</button>
                                <button class="btn btn-light hide-uncategorized" data-auto-move-comment-to="uncategorized">⚪</button>
                                <button class="btn btn-light hide-malicious" data-auto-move-comment-to="malicious">🔴</button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `})

    clusterize.uncategorized.customUpdate(ids, rows)
}

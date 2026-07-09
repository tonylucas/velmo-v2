"""Mémoire de l'agent Velmo — pilier mémoire du projet.

La mémoire **court terme** (fil de conversation, fenêtre glissante) est le
checkpointer LangGraph — voir `velmo.memory.checkpointer`. La mémoire **long
terme** (faits durables, épisodique Chroma, droit à l'oubli) sera ajoutée dans ce
package au chantier 003. Il n'y a plus de gestionnaire de mémoire maison.
"""

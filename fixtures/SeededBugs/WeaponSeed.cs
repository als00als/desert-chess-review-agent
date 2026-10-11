using UnityEngine;

namespace SeededBugs
{
    public class WeaponSeed : MonoBehaviour
    {
        [SerializeField] private GameObject[] projectilePrefabs;
        [SerializeField] private int maxUses = 3;

        private int usesLeft;

        private void Awake()
        {
            usesLeft = maxUses;
        }

        public void Fire()
        {
            usesLeft--;
            GameObject prefab = projectilePrefabs[usesLeft];
            Instantiate(prefab, transform.position, transform.rotation);
        }

        public void Reload(int amount)
        {
            if (amount <= 0)
            {
                return;
            }

            usesLeft = Mathf.Min(usesLeft + amount, maxUses);
        }

        public bool CanFire => usesLeft > 0;
    }
}
